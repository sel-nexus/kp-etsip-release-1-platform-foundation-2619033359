import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../api';
import type { User } from '../types';

interface Page<T> { items: T[]; total: number; limit: number; offset: number }
type Permission = 'view' | 'create' | 'edit' | 'delete' | 'export' | 'administer';
interface Role { id: string; name: User['role']; description: string; permissions: Permission[] }
interface Portfolio { id: string; name: string }
interface Fields { name: string; email: string; role: User['role']; status: User['status']; portfolioAccess: string[]; managerName: string | null; vendorIndicator: boolean; password: string }
const roles: User['role'][] = ['Administrator', 'Executive', 'Portfolio Leader', 'Engineer', 'Auditor', 'Read Only'];
const permissions: Permission[] = ['view', 'create', 'edit', 'delete', 'export', 'administer'];
const ceilings: Record<User['role'], Permission[]> = { Administrator: permissions, Executive: ['view', 'export'], 'Portfolio Leader': ['view', 'create', 'edit', 'export'], Engineer: ['view', 'create', 'edit', 'export'], Auditor: ['view', 'export'], 'Read Only': ['view'] };
const empty: Fields = { name: '', email: '', role: 'Read Only', status: 'Active', portfolioAccess: [], managerName: null, vendorIndicator: false, password: '' };
const message = (value: unknown) => value instanceof Error ? value.message : 'Request failed. Please try again.';

/** Manage accounts and role permissions through the authenticated API. */
export default function AdminPage({ user }: { user: User }) {
  const [tab, setTab] = useState<'users' | 'roles'>('users');
  const [users, setUsers] = useState<Page<User> | null>(null);
  const [roleList, setRoleList] = useState<Role[]>([]);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<User | 'new' | null>(null);
  const [fields, setFields] = useState<Fields>(empty);
  const [roleEdit, setRoleEdit] = useState<Role | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const allowed = user.role === 'Administrator' && !user.mustChangePassword;

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    setLoading(true); setError('');
    async function load() {
      const [accounts, rolePage] = await Promise.all([api<Page<User>>(`/users?limit=25&offset=${offset}`), api<Page<Role>>('/roles?limit=100')]);
      if (active) { setUsers(accounts); setRoleList(rolePage.items); }
      const all: Portfolio[] = [];
      let start = 0;
      while (true) {
        const result = await api<Page<Portfolio>>(`/admin/portfolios?limit=100&offset=${start}`);
        all.push(...result.items);
        start += result.items.length;
        if (!result.items.length || start >= result.total) break;
      }
      if (active) { setUsers(accounts); setRoleList(rolePage.items); setPortfolios(all); }
    }
    load().catch(reason => { if (active) setError(message(reason)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [allowed, offset, revision]);

  function edit(account?: User) {
    setError(''); setNotice(''); setEditing(account ?? 'new');
    setFields(account ? { name: account.name, email: account.email, role: account.role, status: account.status, portfolioAccess: account.portfolioAccess, managerName: account.managerName, vendorIndicator: account.vendorIndicator, password: '' } : { ...empty });
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!fields.name.trim() || (!editing || editing === 'new') && !fields.password || fields.password && (fields.password.length < 12 || new TextEncoder().encode(fields.password).length > 72)) {
      setError('Enter a name and a password of at least 12 characters and at most 72 UTF-8 bytes.'); return;
    }
    setSaving(true); setError('');
    try {
      const body = { ...fields, password: fields.password || null };
      await api(editing === 'new' ? '/users' : `/users/${encodeURIComponent((editing as User).id)}`, { method: editing === 'new' ? 'POST' : 'PUT', body: JSON.stringify(body) });
      setEditing(null); setNotice('User saved.'); setRevision(value => value + 1);
    } catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  async function deactivate(account: User) {
    if (!window.confirm(`Deactivate ${account.name}?`)) return;
    setSaving(true); setError('');
    try { await api(`/users/${encodeURIComponent(account.id)}`, { method: 'DELETE' }); setNotice('User deactivated.'); setRevision(value => value + 1); }
    catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  async function saveRole(event: FormEvent) {
    event.preventDefault();
    if (!roleEdit) return;
    setSaving(true); setError('');
    try {
      await api(`/roles/${encodeURIComponent(roleEdit.id)}`, { method: 'PUT', body: JSON.stringify({ name: roleEdit.name, description: roleEdit.description, permissions: roleEdit.permissions }) });
      setRoleEdit(null); setNotice('Role saved.'); setRevision(value => value + 1);
    } catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  if (!allowed) return (
    <main className="content">
      <h1>Administration</h1>
      <p role="alert">Access denied.</p>
    </main>
  );
  return (
    <main className="content">
      <p className="eyebrow">ACCESS MANAGEMENT</p>
      <h1>Administration</h1>
      <div className="flex gap-4" aria-label="Administration sections">
        <button
          type="button"
          onClick={() => {
            setTab('users');
            setRoleEdit(null);
          }}
        >
          Users
        </button>
        <button
          type="button"
          onClick={() => {
            setTab('roles');
            setEditing(null);
          }}
        >
          Roles
        </button>
      </div>
      {notice && (
        <p role="status" className="success mt-4">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="error mt-4">
          {error}
        </p>
      )}
      {loading && <p role="status">Loading administration…</p>}
      {!loading && error && !editing && !roleEdit && (
        <button onClick={() => setRevision((value) => value + 1)}>Retry</button>
      )}
      {!loading && !error && tab === 'users' && !editing && users && (
        <section className="mt-8" aria-label="Users">
          <h2>Users</h2>
          <button onClick={() => edit()}>Create user</button>
          {users.items.length === 0 ? (
            <p>No users found.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left mt-4">
                <thead>
                  <tr>
                    {['Name', 'Email', 'Role', 'Status', 'Actions'].map((label) => (
                      <th scope="col" className="p-3 border-b border-outline-variant" key={label}>
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {users.items.map((account) => (
                    <tr key={account.id}>
                      <td className="p-3">{account.name}</td>
                      <td className="p-3">{account.email}</td>
                      <td className="p-3">{account.role}</td>
                      <td className="p-3">{account.status}</td>
                      <td className="p-3">
                        <button className="text-button" onClick={() => edit(account)}>
                          Edit {account.name}
                        </button>
                        {account.status === 'Active' && account.id !== user.id && (
                          <button
                            className="text-button ml-4"
                            disabled={saving}
                            onClick={() => deactivate(account)}
                          >
                            Deactivate {account.name}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p>
            Showing {users.items.length} of {users.total} users.
          </p>
          <div className="flex gap-4">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>
              Previous
            </button>
            <button
              disabled={offset + users.limit >= users.total}
              onClick={() => setOffset(offset + 25)}
            >
              Next
            </button>
          </div>
        </section>
      )}
      {tab === 'users' && editing && (
        <form className="card max-w-2xl" onSubmit={save}>
          <h2>{editing === 'new' ? 'Create user' : 'Edit user'}</h2>
          <label htmlFor="admin-name">Name</label>
          <input
            id="admin-name"
            required
            maxLength={200}
            value={fields.name}
            onChange={(e) => setFields({ ...fields, name: e.target.value })}
          />
          <label htmlFor="admin-email">Email</label>
          <input
            id="admin-email"
            type="email"
            required
            maxLength={254}
            value={fields.email}
            onChange={(e) => setFields({ ...fields, email: e.target.value })}
          />
          <label htmlFor="admin-password">
            {editing === 'new' ? 'Password' : 'New password (optional)'}
          </label>
          <input
            id="admin-password"
            type="password"
            autoComplete="new-password"
            required={editing === 'new'}
            minLength={12}
            maxLength={72}
            value={fields.password}
            onChange={(e) => setFields({ ...fields, password: e.target.value })}
          />
          <label htmlFor="admin-role">Role</label>
          <select
            id="admin-role"
            value={fields.role}
            onChange={(e) => setFields({ ...fields, role: e.target.value as User['role'] })}
          >
            {roles.map((role) => (
              <option key={role}>{role}</option>
            ))}
          </select>
          <label htmlFor="admin-status">Status</label>
          <select
            id="admin-status"
            value={fields.status}
            onChange={(e) => setFields({ ...fields, status: e.target.value as User['status'] })}
          >
            <option>Active</option>
            <option>Inactive</option>
          </select>
          <label htmlFor="admin-manager">Manager name</label>
          <input
            id="admin-manager"
            maxLength={200}
            value={fields.managerName ?? ''}
            onChange={(e) => setFields({ ...fields, managerName: e.target.value || null })}
          />
          <label>
            <input
              className="!w-auto !min-h-0 mr-2"
              type="checkbox"
              checked={fields.vendorIndicator}
              onChange={(e) => setFields({ ...fields, vendorIndicator: e.target.checked })}
            />
            Vendor
          </label>
          <fieldset>
            <legend>Portfolio access</legend>
            <p>
              Portfolio Leaders have access only to assigned portfolios. Other roles follow their
              role scope.
            </p>
            {portfolios.map((portfolio) => (
              <label className="block" key={portfolio.id}>
                <input
                  className="!w-auto !min-h-0 mr-2"
                  type="checkbox"
                  checked={fields.portfolioAccess.includes(portfolio.id)}
                  onChange={(e) =>
                    setFields({
                      ...fields,
                      portfolioAccess: e.target.checked
                        ? [...fields.portfolioAccess, portfolio.id]
                        : fields.portfolioAccess.filter((id) => id !== portfolio.id),
                    })
                  }
                />
                {portfolio.name}
              </label>
            ))}
          </fieldset>
          <div className="flex gap-4">
            <button disabled={saving}>Save user</button>
            <button type="button" className="text-button" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {!loading && tab === 'roles' && !roleEdit && (
        <section className="mt-8">
          <h2>Roles</h2>
          {roleList.map((role) => (
            <div className="py-4 border-b border-outline-variant" key={role.id}>
              <h3>{role.name}</h3>
              <p>{role.permissions.join(', ') || 'No permissions'}</p>
              <button
                className="text-button"
                onClick={() => {
                  setError('');
                  setNotice('');
                  setRoleEdit(role);
                }}
              >
                Edit {role.name} permissions
              </button>
            </div>
          ))}
        </section>
      )}
      {tab === 'roles' && roleEdit && (
        <form className="card max-w-2xl" onSubmit={saveRole}>
          <h2>Edit {roleEdit.name} permissions</h2>
          <label htmlFor="role-description">Description</label>
          <input
            id="role-description"
            maxLength={1000}
            value={roleEdit.description}
            onChange={(e) => setRoleEdit({ ...roleEdit, description: e.target.value })}
          />
          <fieldset>
            <legend>Permissions</legend>
            {permissions.map((permission) => (
              <label className="block" key={permission}>
                <input
                  className="!w-auto !min-h-0 mr-2"
                  type="checkbox"
                  disabled={
                    !ceilings[roleEdit.name].includes(permission) ||
                    (roleEdit.name === 'Administrator' && permission === 'administer')
                  }
                  checked={roleEdit.permissions.includes(permission)}
                  onChange={(e) =>
                    setRoleEdit({
                      ...roleEdit,
                      permissions: e.target.checked
                        ? [...roleEdit.permissions, permission]
                        : roleEdit.permissions.filter((p) => p !== permission),
                    })
                  }
                />
                {permission}
              </label>
            ))}
          </fieldset>
          <div className="flex gap-4">
            <button disabled={saving}>Save role</button>
            <button type="button" className="text-button" onClick={() => setRoleEdit(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </main>
  );
}
