export const roundHalfToEven = (value: number): number => {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff < 0.5) {
    return floor;
  }
  if (diff > 0.5) {
    return floor + 1;
  }
  return floor % 2 === 0 ? floor : floor + 1;
};

export const formatLongDuration = (seconds: number): string => {
  const minutes = seconds / 60;
  if (minutes < 35) {
    const rounded = Math.max(roundHalfToEven(minutes / 5) * 5, 5);
    return `${rounded} min`;
  }
  if (minutes < 75) {
    return "1 Hour";
  }
  if (minutes < 105) {
    return "1.5 Hours";
  }
  if (minutes < 135) {
    return "2 Hours";
  }
  const roundedHalfHours = roundHalfToEven((minutes / 60) * 2) / 2;
  return `${roundedHalfHours} Hours`;
};

export const formatCompactDuration = (seconds: number): string => {
  const minutes = seconds / 60;
  if (minutes < 35) {
    return `${Math.max(roundHalfToEven(minutes / 5) * 5, 5)}m`;
  }
  return `${roundHalfToEven((minutes / 60) * 2) / 2}h`;
};
