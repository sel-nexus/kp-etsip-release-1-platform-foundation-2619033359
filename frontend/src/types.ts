/** Public identity returned by the API; password hashes never cross this boundary. */
export interface User {
  id: string;
  name: string;
  email: string;
  role: 'Administrator' | 'Executive' | 'Portfolio Leader' | 'Engineer' | 'Auditor' | 'Read Only';
  portfolioAccess: string[];
  status: 'Active' | 'Inactive';
  authSource: 'local';
  managerName: string | null;
  vendorIndicator: boolean;
  lastLogin: string | null;
  mustChangePassword: boolean;
  defaultLandingPage: 'dashboard' | 'applications' | null;
}
export interface Session { token: string; user: User }
