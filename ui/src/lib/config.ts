export interface AppConfig {
  auth0Domain: string;
  auth0ClientId: string;
  auth0Audience: string;
  apiBaseUrl: string;
  isAuthEnabled: boolean;
}

export const appConfig: AppConfig = {
  auth0Domain: import.meta.env.VITE_AUTH0_DOMAIN || "",
  auth0ClientId: import.meta.env.VITE_AUTH0_CLIENT_ID || "",
  auth0Audience: import.meta.env.VITE_AUTH0_AUDIENCE || "",
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || "",
  get isAuthEnabled(): boolean {
    return Boolean(this.auth0Domain && this.auth0ClientId);
  },
};
