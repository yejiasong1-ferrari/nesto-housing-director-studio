"""Vision Agent internal modules.

Five-module pipeline:
1. VideoPreprocessor - build video index (no AI)
2. RoomSegmenter - spatial boundary detection (OpenCLIP embeddings)
3. KeyFrameSelector - select best representative frames (quality scoring)
4. ImageLLMAnalyzer - LLM-based room understanding (only place LLM is called)
5. KnowledgeFusionEngine - multi-frame reasoning and reconciliation
"""
