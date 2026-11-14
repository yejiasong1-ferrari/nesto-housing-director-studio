/** Shared create-pipeline stages for landing and dedicated progress pages. */
export const SAAS_STAGE_DEFS = [
  {
    name: "vision",
    label: "Understanding the property",
    match: /download|prepar|compress|normaliz|vision|understanding|watch/i,
    minProgress: 5,
  },
  {
    name: "story",
    label: "Creating the story & narration",
    match: /script|voice|story|plan|narrat/i,
    minProgress: 30,
  },
  {
    name: "editing",
    label: "Directing the edit",
    match: /edit|direct|timeline/i,
    minProgress: 55,
  },
  {
    name: "evaluation",
    label: "Quality pass & final render",
    match: /render|evaluat|quality|remix|upload|sync|complet/i,
    minProgress: 75,
  },
] as const;
