// Database CRUD, MySQL, PostgreSQL, SQLite, Docker databases, queries

// Database status
export async function getDatabaseStatus() {
    return this.request('/databases/status');
}

// MySQL
export async function getMySQLDatabases(rootPassword = null) {
    const params = rootPassword ? `?root_password=${encodeURIComponent(rootPassword)}` : '';
    return this.request(`/databases/mysql${params}`);
}

export async function createMySQLDatabase(data) {
    return this.request('/databases/mysql', {
        method: 'POST',
        body: data
    });
}

export async function dropMySQLDatabase(name, rootPassword = null) {
    return this.request(`/databases/mysql/${name}`, {
        method: 'DELETE',
        body: { root_password: rootPassword }
    });
}

export async function getMySQLTables(database, rootPassword = null) {
    const params = rootPassword ? `?root_password=${encodeURIComponent(rootPassword)}` : '';
    return this.request(`/databases/mysql/${database}/tables${params}`);
}

export async function backupMySQLDatabase(database, rootPassword = null) {
    return this.request(`/databases/mysql/${database}/backup`, {
        method: 'POST',
        body: { root_password: rootPassword }
    });
}

export async function restoreMySQLDatabase(database, backupPath, rootPassword = null) {
    return this.request(`/databases/mysql/${database}/restore`, {
        method: 'POST',
        body: { backup_path: backupPath, root_password: rootPassword }
    });
}

export async function getMySQLUsers(rootPassword = null) {
    const params = rootPassword ? `?root_password=${encodeURIComponent(rootPassword)}` : '';
    return this.request(`/databases/mysql/users${params}`);
}

export async function createMySQLUser(data) {
    return this.request('/databases/mysql/users', {
        method: 'POST',
        body: data
    });
}

export async function dropMySQLUser(username, host = 'localhost', rootPassword = null) {
    return this.request(`/databases/mysql/users/${username}`, {
        method: 'DELETE',
        body: { host, root_password: rootPassword }
    });
}

export async function grantMySQLPrivileges(username, database, privileges = 'ALL', host = 'localhost', rootPassword = null) {
    return this.request(`/databases/mysql/users/${username}/grant`, {
        method: 'POST',
        body: { database, privileges, host, root_password: rootPassword }
    });
}

// PostgreSQL
export async function getPostgreSQLDatabases() {
    return this.request('/databases/postgresql');
}

export async function createPostgreSQLDatabase(data) {
    return this.request('/databases/postgresql', {
        method: 'POST',
        body: data
    });
}

export async function dropPostgreSQLDatabase(name) {
    return this.request(`/databases/postgresql/${name}`, { method: 'DELETE' });
}

export async function getPostgreSQLTables(database) {
    return this.request(`/databases/postgresql/${database}/tables`);
}

export async function backupPostgreSQLDatabase(database) {
    return this.request(`/databases/postgresql/${database}/backup`, { method: 'POST' });
}

export async function restorePostgreSQLDatabase(database, backupPath) {
    return this.request(`/databases/postgresql/${database}/restore`, {
        method: 'POST',
        body: { backup_path: backupPath }
    });
}

export async function getPostgreSQLUsers() {
    return this.request('/databases/postgresql/users');
}

export async function createPostgreSQLUser(data) {
    return this.request('/databases/postgresql/users', {
        method: 'POST',
        body: data
    });
}

export async function dropPostgreSQLUser(username) {
    return this.request(`/databases/postgresql/users/${username}`, { method: 'DELETE' });
}

export async function grantPostgreSQLPrivileges(username, database, privileges = 'ALL') {
    return this.request(`/databases/postgresql/users/${username}/grant`, {
        method: 'POST',
        body: { database, privileges }
    });
}

// Backups
export async function getDatabaseBackups(type = null) {
    const params = type ? `?type=${type}` : '';
    return this.request(`/databases/backups${params}`);
}

export async function deleteDatabaseBackup(filename) {
    return this.request(`/databases/backups/${filename}`, { method: 'DELETE' });
}

export async function generateDatabasePassword(length = 16) {
    return this.request(`/databases/generate-password?length=${length}`);
}

// Query Execution
export async function executeMySQLQuery(database, query, readonly = true) {
    return this.request(`/databases/mysql/${database}/query`, {
        method: 'POST',
        body: { query, readonly }
    });
}

export async function executePostgreSQLQuery(database, query, readonly = true) {
    return this.request(`/databases/postgresql/${database}/query`, {
        method: 'POST',
        body: { query, readonly }
    });
}

export async function executeSQLiteQuery(path, query, readonly = true) {
    return this.request('/databases/sqlite/query', {
        method: 'POST',
        body: { path, query, readonly }
    });
}

export async function getMySQLTableStructure(database, table) {
    return this.request(`/databases/mysql/${database}/tables/${table}/structure`);
}

export async function getPostgreSQLTableStructure(database, table) {
    return this.request(`/databases/postgresql/${database}/tables/${table}/structure`);
}

export async function getSQLiteTableStructure(path, table) {
    return this.request(`/databases/sqlite/tables/${table}/structure?path=${encodeURIComponent(path)}`);
}

export async function getSQLiteDatabases() {
    return this.request('/databases/sqlite');
}

export async function getSQLiteTables(path) {
    return this.request(`/databases/sqlite/tables?path=${encodeURIComponent(path)}`);
}

// Docker Container Databases
export async function getDockerDatabases() {
    return this.request('/databases/docker');
}

// Flat list of databases discovered across all Docker apps, tagged with engine
// + owning app — used to surface containerised DBs under their engine node.
export async function getAllDockerDatabases() {
    return this.request('/databases/docker/databases');
}

export async function getAppDatabases(appId) {
    return this.request(`/databases/docker/app/${appId}`);
}

export async function getDockerContainerDatabases(container, password = null) {
    const headers = password ? { 'X-DB-Password': password } : {};
    return this.request(`/databases/docker/${container}/databases`, { headers });
}

export async function getDockerDatabaseTables(container, database, password = null, user = null) {
    const headers = password ? { 'X-DB-Password': password } : {};
    const params = user ? `?user=${encodeURIComponent(user)}` : '';
    return this.request(`/databases/docker/${container}/${database}/tables${params}`, { headers });
}

export async function executeDockerQuery(container, database, query, password = null, readonly = true, user = null) {
    const headers = password ? { 'X-DB-Password': password } : {};
    return this.request(`/databases/docker/${container}/${database}/query`, {
        method: 'POST',
        body: { query, readonly, password, user },
        headers
    });
}

// Database Migrations
export async function getMigrationStatus() {
    return this.request('/migrations/status');
}

export async function createMigrationBackup() {
    return this.request('/migrations/backup', { method: 'POST' });
}

export async function applyMigrations() {
    return this.request('/migrations/apply', { method: 'POST' });
}

export async function getMigrationHistory() {
    return this.request('/migrations/history');
}

// Managed databases — durable tracking beside the live introspection. Secrets
// are never returned (has_secret); the connection URI is revealed only via an
// explicit, audited action.
export async function getManagedDatabases() {
    return this.request('/databases/managed');
}

export async function getManagedDatabase(id) {
    return this.request(`/databases/managed/${id}`);
}

export async function createManagedDatabase(data) {
    return this.request('/databases/managed', { method: 'POST', body: data });
}

export async function adoptManagedDatabase(data) {
    return this.request('/databases/managed/adopt', { method: 'POST', body: data });
}

export async function deleteManagedDatabase(id, { drop = false } = {}) {
    const q = drop ? '?drop=true' : '';
    return this.request(`/databases/managed/${id}${q}`, { method: 'DELETE' });
}

export async function revealManagedConnectionUri(id) {
    return this.request(`/databases/managed/${id}/connection-uri`, { method: 'POST' });
}

export async function protectManagedDatabase(id, policy = null) {
    return this.request(`/databases/managed/${id}/protect`, { method: 'POST', body: { policy } });
}

// Managed database users — tracked rows merged with the live engine list.
// create returns the password exactly once; it is never stored or re-exposed.
export async function getManagedDbUsers(id) {
    return this.request(`/managed-databases/${id}/users`);
}

export async function createManagedDbUser(id, data) {
    return this.request(`/managed-databases/${id}/users`, { method: 'POST', body: data });
}

export async function deleteManagedDbUser(id, userId) {
    return this.request(`/managed-databases/${id}/users/${userId}`, { method: 'DELETE' });
}

// One-click Adminer SSO — mints a 5-minute single-database credential and
// returns the launch descriptor the caller form-POSTs into Adminer.
export async function launchManagedDbSso(id) {
    return this.request(`/managed-databases/${id}/sso`, { method: 'POST' });
}

// Database engines. An engine is an app template carrying an `engine:` block,
// so this is a view over the template catalog plus the apps installed from it —
// `{ catalog: [...], installed: [...] }`. Installing delegates to the ordinary
// template install pipeline and answers with the app and its deployment job, so
// the caller navigates to the deploy console like any other template install.
//
// Lifecycle (start / stop / uninstall) is app lifecycle: use the app endpoints.
//
// `live` asks the backend to probe each installed engine's container. Callers
// that only need identity and install variables (resolving which app an engine
// is, say) pass false and skip a Docker round-trip per engine.
export async function getDatabaseEngines(live = true) {
    return this.request(`/databases/engines${live ? '' : '?live=false'}`);
}

export async function installDatabaseEngine(payload) {
    return this.request('/databases/engines', { method: 'POST', body: payload });
}
