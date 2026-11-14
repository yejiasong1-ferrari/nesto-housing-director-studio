"""Module 4: Image LLM Analysis.

The ONLY module in Vision Agent that calls an LLM.

Sends representative keyframe images to a vision-capable LLM
with a structured prompt that extracts:
- Room type and confidence
- Decoration style
- Lighting quality
- Layout type
- Furniture and appliances
- Selling points
- Camera motion description

The LLM does NOT generate marketing copy.
It only returns objective facts about what it sees.

This module produces per-frame RoomKnowledge. The final unified
knowledge is produced by Module 5 (Knowledge Fusion Engine).
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from backend.schemas.vision_schema import CameraKnowledge, RoomKnowledge
from backend.services.llm.base import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a professional real estate analyst.
You analyze rooms from property walkthrough videos.

Your ONLY job is to understand what you see. You NEVER generate marketing copy.
You ONLY return objective, factual observations.

For each image set, return a JSON object with:
- room_type: Primary room label for the segment (e.g. "Living Room", "Kitchen", "Bedroom", "Bathroom", "Hallway", "Dining Room", "Study Room", "Laundry Room", "Garage", "Balcony", "Closet"). If frames clearly show MULTIPLE different rooms, use "Mixed Private Area" or "Unknown" — do NOT force a single bedroom/kitchen label.
- confidence: How confident you are in the primary room_type (0.0 to 1.0)
- style: Decoration style (e.g. "Modern", "Traditional", "Contemporary", "Rustic", "Minimalist", "Industrial")
- layout: Layout description (e.g. "Open", "Enclosed", "L-shaped", "Galley", "Split-level")
- lighting: Lighting quality (e.g. "Excellent", "Good", "Fair", "Poor")
- selling_points: List of notable features that would appeal to buyers (be specific, e.g. "Kitchen Island", "Bosch Built-in Oven", "Glass-enclosed shower")
- furniture: List of visible furniture items
- appliances: List of visible appliances
- camera: Object with "motion" (Forward/Pan Left/Pan Right/Static/Tilt Up/Tilt Down) and "speed" (Slow/Medium/Fast)
- notes: Any additional observations, especially secondary rooms briefly visible in the same segment

Important:
- Do not let one dominant room override clearly visible secondary rooms.
- If a bathroom, bedroom, or other distinct space is clearly visible even briefly, mention its fixtures in selling_points / furniture / appliances / notes (e.g. toilet, shower, vanity) even when room_type remains the primary space.
- Prefer "Mixed Private Area" when two or more distinct rooms are clearly visible across the frames.

Return ONLY valid JSON. No markdown. No explanation. No marketing language."""


class ImageLLMAnalyzer:
    """Analyzes room images using a vision-capable LLM.

    Sends representative keyframes to the LLM and parses
    structured RoomKnowledge from the response.
    """

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        """Initialize the analyzer.

        Args:
            llm_provider: LLM provider to use. If None, will attempt
                to create an OpenAI provider from environment.
        """
        self.llm_provider = llm_provider

    def _ensure_provider(self) -> LLMProvider:
        """Lazy-initialize LLM provider."""
        if self.llm_provider is not None:
            return self.llm_provider

        # Default to OpenAI
        from backend.services.llm.openai_provider import OpenAIProvider

        self.llm_provider = OpenAIProvider()
        return self.llm_provider

    def encode_image(self, image_path: str | Path) -> str:
        """Encode an image file as base64 for API submission.

        Args:
            image_path: Path to the image file.

        Returns:
            Base64-encoded string.
        """
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def build_analysis_prompt(
        self, keyframe_paths: list[str], attention_hint: str = ""
    ) -> list[dict[str, Any]]:
        """Build the LLM messages for room analysis.

        Args:
            keyframe_paths: Paths to representative keyframe images.
            attention_hint: Optional user hint (e.g. "focus on kitchen").

        Returns:
            List of message dicts for the LLM API.
        """
        content_parts = []

        # Add text instruction
        instruction = "Analyze this room from a real estate walkthrough video."
        if attention_hint:
            instruction += f"\nAttention hint: {attention_hint} (describe this area in more detail if applicable)"
        instruction += "\nReturn ONLY the JSON analysis."

        content_parts.append({"type": "text", "text": instruction})

        # Add images
        for path in keyframe_paths:
            b64 = self.encode_image(path)
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "high",
                },
            })

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content_parts},
        ]
        return messages

    def parse_llm_response(self, response_text: str) -> RoomKnowledge:
        """Parse LLM response into structured RoomKnowledge.

        Args:
            response_text: Raw LLM response text.

        Returns:
            RoomKnowledge object.
        """
        # Try to extract JSON from the response
        text = response_text.strip()

        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {text[:200]}")
            return RoomKnowledge(notes=f"Parse error: {text[:200]}")

        # LLM may return one object or a list of per-image analyses
        if isinstance(data, list):
            analyses = [
                self._parse_room_dict(item)
                for item in data
                if isinstance(item, dict)
            ]
            if not analyses:
                return RoomKnowledge(notes="Parse error: JSON list contained no objects")
            if len(analyses) == 1:
                return analyses[0]

            from backend.agents.vision.modules.fusion import KnowledgeFusionEngine

            return KnowledgeFusionEngine().fuse_segment("?", analyses)

        if not isinstance(data, dict):
            return RoomKnowledge(notes=f"Parse error: unexpected JSON type {type(data).__name__}")

        return self._parse_room_dict(data)

    def _parse_room_dict(self, data: dict[str, Any]) -> RoomKnowledge:
        """Parse a single room analysis dict into RoomKnowledge."""

        def _coerce_str(value: Any) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return "; ".join(str(v) for v in value)
            return str(value) if value is not None else ""

        def _coerce_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(v) for v in value]
            if isinstance(value, str):
                return [value]
            return []

        camera_data = data.get("camera", {})
        if isinstance(camera_data, list):
            camera = CameraKnowledge()
        elif isinstance(camera_data, dict):
            camera = CameraKnowledge(
                motion=_coerce_str(camera_data.get("motion", "")),
                speed=_coerce_str(camera_data.get("speed", "")),
                stability=_coerce_str(camera_data.get("stability", "")),
            )
        else:
            camera = CameraKnowledge()

        return RoomKnowledge(
            room_type=_coerce_str(data.get("room_type", "Unknown")) or "Unknown",
            confidence=float(data.get("confidence", 0.0) or 0.0),
            style=_coerce_str(data.get("style", "")),
            layout=_coerce_str(data.get("layout", "")),
            lighting=_coerce_str(data.get("lighting", "")),
            selling_points=_coerce_list(data.get("selling_points", [])),
            furniture=_coerce_list(data.get("furniture", [])),
            appliances=_coerce_list(data.get("appliances", [])),
            camera=camera,
            notes=_coerce_str(data.get("notes", "")),
        )

    async def analyze_segment(
        self,
        keyframe_paths: list[str],
        attention_hint: str = "",
    ) -> RoomKnowledge:
        """Analyze a single segment using its keyframes.

        Args:
            keyframe_paths: Paths to keyframe images for this segment.
            attention_hint: Optional user attention hint.

        Returns:
            RoomKnowledge for this segment.
        """
        if not keyframe_paths:
            return RoomKnowledge(room_type="Unknown", confidence=0.0)

        provider = self._ensure_provider()

        try:
            # Use generate_vision for proper multimodal API call
            # OpenAIProvider.generate_vision handles image encoding
            from backend.services.llm.openai_provider import OpenAIProvider

            if isinstance(provider, OpenAIProvider):
                response = await provider.generate_vision(
                    system_prompt=SYSTEM_PROMPT,
                    text_content=self._build_instruction(attention_hint),
                    image_paths=keyframe_paths,
                    temperature=0.1,
                    max_tokens=2048,
                )
                return self.parse_llm_response(response.content)
            else:
                # Generic LLM provider fallback
                messages = self.build_analysis_prompt(keyframe_paths, attention_hint)
                llm_messages = []
                for msg in messages:
                    if isinstance(msg["content"], str):
                        llm_messages.append(LLMMessage(role=msg["role"], content=msg["content"]))
                    else:
                        llm_messages.append(
                            LLMMessage(role=msg["role"], content=str(msg["content"]))
                        )

                response = await provider.generate(
                    messages=llm_messages,
                    temperature=0.1,
                    max_tokens=1024,
                )
                return self.parse_llm_response(response.content)

        except Exception as e:
            logger.error(f"LLM analysis failed: {e}", exc_info=True)
            return RoomKnowledge(
                room_type="Unknown",
                confidence=0.0,
                notes=f"Analysis error: {str(e)}",
            )

    def _build_instruction(self, attention_hint: str = "") -> str:
        """Build the text instruction for the LLM."""
        instruction = "Analyze this room from a real estate walkthrough video."
        if attention_hint:
            instruction += f"\nAttention hint: {attention_hint} (describe this area in more detail if applicable)"
        instruction += "\nReturn ONLY the JSON analysis."
        return instruction

    async def analyze_all_segments(
        self,
        segments_with_keyframes: list[dict[str, Any]],
        attention_hint: str = "",
    ) -> list[RoomKnowledge]:
        """Analyze all segments.

        Args:
            segments_with_keyframes: List of dicts with segment_id and keyframes.
            attention_hint: Optional user attention hint.

        Returns:
            List of RoomKnowledge, one per segment.
        """
        results = []
        for seg_info in segments_with_keyframes:
            seg_id = seg_info.get("segment_id", "?")
            keyframes = seg_info.get("keyframes", [])

            logger.info(f"Analyzing segment {seg_id} with {len(keyframes)} keyframes")

            knowledge = await self.analyze_segment(keyframes, attention_hint)
            results.append(knowledge)

            logger.info(
                f"Segment {seg_id}: {knowledge.room_type} "
                f"(confidence: {knowledge.confidence:.2f})"
            )

        return results
