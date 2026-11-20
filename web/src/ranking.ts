export const similarPriority = (score: number, listeners: number | null) =>
  score / Math.max(listeners ?? 1, 1) ** 0.1;
