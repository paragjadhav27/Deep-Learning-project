import type { TargetAgeGroup, Task } from "@/lib/api/client";

export type ToolSlug = "age" | "presentation" | "aging";

export interface ToolDefinition {
  slug: ToolSlug;
  task: Task;
  name: string;
  /** Primary action label, e.g. on the landing page and submit button. */
  action: string;
  summary: string;
  whatItReturns: string;
  limitations: string[];
}

const SHARED_LIMITS = [
  "Not suitable for hiring, policing, access control, healthcare, or any decision about a person.",
  "Doesn't identify anyone, and never compares faces across photos.",
];

export const TOOLS: Record<ToolSlug, ToolDefinition> = {
  age: {
    slug: "age",
    task: "age_estimation",
    name: "Age estimate",
    action: "Estimate age",
    summary: "An approximate age range for how old the person in a photo appears.",
    whatItReturns:
      "A range of years with an uncertainty band. It reflects apparent age in this photo, not a verified or legal age.",
    limitations: [
      "Lighting, makeup, facial hair, camera angle, and image quality can shift the estimate by years.",
      "Accuracy can differ across skin tones, ages, and presentation styles.",
      "Never use it to verify age or eligibility.",
      ...SHARED_LIMITS,
    ],
  },
  presentation: {
    slug: "presentation",
    task: "presentation_estimation",
    name: "Perceived presentation",
    action: "Estimate perceived presentation",
    summary:
      "How a model perceives the gender presentation in a photo. It says nothing about who someone is.",
    whatItReturns:
      "A position on a spectrum between feminine-presenting and masculine-presenting, or \"uncertain\". It describes how the photo appears to a model, not a person's gender identity or sex.",
    limitations: [
      "Presentation is how a photo looks. It is not gender identity, and not sex.",
      "The model was trained on binary labels. It can't represent the full range of how people present, so it often answers \"uncertain\".",
      "Accuracy can differ across skin tones, ages, cultures, and styles (hair, makeup, clothing).",
      ...SHARED_LIMITS,
    ],
  },
  aging: {
    slug: "aging",
    task: "age_transformation",
    name: "Age transformation preview",
    action: "Preview age transformation",
    summary: "A synthetic, illustrative image of the photo edited toward a chosen age group.",
    whatItReturns:
      "A generated image, clearly marked as synthetic. It's a creative illustration, not a prediction of how anyone looked or will look.",
    limitations: [
      "Generated images are artificial. They don't predict real appearance.",
      "Results can change skin tone, features, or expression in unrealistic ways.",
      "Don't use generated images to impersonate or mislead anyone.",
      ...SHARED_LIMITS,
    ],
  },
};

export const TOOL_ORDER: ToolSlug[] = ["age", "presentation", "aging"];

export function isToolSlug(value: string): value is ToolSlug {
  return value in TOOLS;
}

export const TARGET_GROUP_LABELS: Record<TargetAgeGroup, { label: string; hint: string }> = {
  child: { label: "Child", hint: "Roughly under 13" },
  teen: { label: "Teen", hint: "Roughly 13–19" },
  young_adult: { label: "Young adult", hint: "Roughly 20–35" },
  middle_aged_adult: { label: "Middle-aged adult", hint: "Roughly 36–59" },
  older_adult: { label: "Older adult", hint: "Roughly 60 and over" },
};

export const STAGE_LABELS: Record<string, string> = {
  preparing: "Preparing your photo",
  detecting_face: "Checking for a single face",
  estimating: "Running the estimate",
  rendering: "Generating the illustrative image",
};
