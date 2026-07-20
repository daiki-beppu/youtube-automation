export interface SunoNotificationPayload {
  kind: "success" | "error";
  message: string;
}

interface NotificationOptions {
  type: "basic";
  iconUrl: string;
  title: string;
  message: string;
  silent: boolean;
}

interface NotificationDependencies {
  create: (options: NotificationOptions) => Promise<string>;
  getUrl: (path: string) => string;
}

export async function showSunoNotification(
  payload: SunoNotificationPayload,
  dependencies: NotificationDependencies = {
    create: (options) => browser.notifications.create(options),
    getUrl: (path) => chrome.runtime.getURL(path),
  }
): Promise<void> {
  await dependencies.create({
    type: "basic",
    iconUrl: dependencies.getUrl("/icon/48.png"),
    title: "Suno Helper",
    message: payload.message,
    silent: true,
  });
}
