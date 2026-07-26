// Statement builders for the "new table / collection / index" flow.
//
// Everything here is pure: given a target and a list of columns it returns the
// exact text that will be sent to the database, so the modal can show the
// operator the statement before anything runs. Nothing in this file talks to
// the network.
//
// Two safety rules hold for every generator:
//
//  * identifiers are validated against `IDENT_RE` and then quoted with
//    `quoteIdent()` — they are never concatenated raw;
//  * a default value is encoded as a *literal* (number, allow-listed keyword,
//    or a quoted string), so free text can never become SQL.

import { quoteIdent } from './dbAdapter';

// Longest identifier PostgreSQL accepts without silently truncating; MySQL
// (64) and SQLite (unbounded) are both happy inside it.
export const IDENT_MAX = 63;
export const IDENT_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function identError(value, what = 'Name') {
    const v = String(value || '').trim();
    if (!v) return `${what} is required.`;
    if (v.length > IDENT_MAX) return `${what} is longer than ${IDENT_MAX} characters.`;
    if (!IDENT_RE.test(v)) {
        return `${what} may only contain letters, digits and underscores, and cannot start with a digit.`;
    }
    return null;
}

// ─── SQL dialects ────────────────────────────────────────────
// Only the three ServerKit can actually execute against. `integers` drives the
// auto-increment substitution: a primary key on one of these types becomes the
// dialect's own generated-key form.
export const SQL_DIALECTS = {
    mysql: {
        label: 'MySQL',
        types: ['BIGINT', 'INT', 'SMALLINT', 'DECIMAL(10,2)', 'DOUBLE', 'VARCHAR(255)', 'VARCHAR(64)', 'TEXT', 'BOOLEAN', 'DATE', 'DATETIME', 'TIMESTAMP', 'JSON'],
        integers: ['BIGINT', 'INT', 'SMALLINT'],
        keyType: 'BIGINT',
        textType: 'VARCHAR(255)',
        stampType: 'TIMESTAMP',
        keyNote: 'AUTO_INCREMENT',
    },
    postgresql: {
        label: 'PostgreSQL',
        types: ['BIGINT', 'INTEGER', 'SMALLINT', 'NUMERIC(10,2)', 'DOUBLE PRECISION', 'VARCHAR(255)', 'TEXT', 'BOOLEAN', 'DATE', 'TIMESTAMP', 'TIMESTAMPTZ', 'JSONB', 'UUID'],
        integers: ['BIGINT', 'INTEGER', 'SMALLINT'],
        keyType: 'BIGINT',
        textType: 'VARCHAR(255)',
        stampType: 'TIMESTAMPTZ',
        keyNote: 'BIGSERIAL',
    },
    sqlite: {
        label: 'SQLite',
        types: ['INTEGER', 'TEXT', 'REAL', 'NUMERIC', 'BLOB'],
        integers: ['INTEGER'],
        keyType: 'INTEGER',
        textType: 'TEXT',
        stampType: 'TEXT',
        keyNote: 'AUTOINCREMENT',
    },
};

// Which dialect a connection speaks, or null when ServerKit has no way to run
// a statement against it. A Docker connection is executed through the
// container's mysql/mariadb client, so a containerised PostgreSQL has no path.
export function dialectOf(conn) {
    if (!conn) return null;
    if (conn.dbType === 'mysql') return 'mysql';
    if (conn.dbType === 'postgresql') return 'postgresql';
    if (conn.dbType === 'sqlite') return 'sqlite';
    if (conn.dbType === 'docker') {
        return conn.dockerType === 'postgresql' ? null : 'mysql';
    }
    return null;
}

// Keywords that may appear in a DEFAULT unquoted. Deliberately short: every
// entry has to be valid in all three dialects, which is why CURRENT_DATE is
// absent (MySQL needs it parenthesised).
const DEFAULT_KEYWORDS = new Map([
    ['NULL', 'NULL'],
    ['TRUE', 'TRUE'],
    ['FALSE', 'FALSE'],
    ['CURRENT_TIMESTAMP', 'CURRENT_TIMESTAMP'],
    ['NOW()', 'CURRENT_TIMESTAMP'],
    ['NOW', 'CURRENT_TIMESTAMP'],
]);

export const DEFAULT_KEYWORD_LIST = ['NULL', 'TRUE', 'FALSE', 'CURRENT_TIMESTAMP'];

// MySQL treats a backslash as an escape inside a string literal, so a trailing
// backslash would otherwise consume the closing quote. PostgreSQL and SQLite
// take backslashes literally, and doubling them there would change the value.
function quoteLiteral(dialect, value) {
    const escaped = dialect === 'mysql'
        ? value.replace(/\\/g, '\\\\').replace(/'/g, "''")
        : value.replace(/'/g, "''");
    return `'${escaped}'`;
}

// Free text in, a literal out — never an expression. This is what keeps the
// "Default" cell from being an SQL injection point.
export function encodeDefault(dialect, raw) {
    const v = String(raw ?? '').trim();
    if (!v) return null;
    const keyword = DEFAULT_KEYWORDS.get(v.toUpperCase());
    if (keyword) return keyword;
    if (/^-?\d+(\.\d+)?$/.test(v)) return v;
    return quoteLiteral(dialect, v);
}

export function emptyColumn(dialect) {
    return { name: '', type: SQL_DIALECTS[dialect]?.textType || 'TEXT', pk: false, notNull: false, def: '' };
}

// Starter rows, so the grid opens on something shaped like a real table rather
// than on one blank line.
export function starterColumns(dialect) {
    const d = SQL_DIALECTS[dialect] || SQL_DIALECTS.sqlite;
    return [
        { name: 'id', type: d.keyType, pk: true, notNull: true, def: '' },
        { name: '', type: d.textType, pk: false, notNull: true, def: '' },
        { name: 'created_at', type: d.stampType, pk: false, notNull: true, def: 'CURRENT_TIMESTAMP' },
    ];
}

// What each family calls its key, and the type that key usually has. Opening a
// document store on `id: String` would be a small lie about how it works.
const FAMILY_STARTERS = {
    Document: { name: '_id', type: 'ObjectId' },
    'Time-series': { name: 'time', type: 'timestamp' },
    Search: { name: 'id', type: 'string' },
    Graph: { name: 'id', type: 'String' },
    'Key-value': { name: 'id', type: 'string' },
};

export function starterFields(family) {
    const types = familyTypes(family);
    const key = FAMILY_STARTERS[family] || { name: 'id', type: types[0] };
    return [
        { name: key.name, type: types.includes(key.type) ? key.type : types[0], pk: true, notNull: true, def: '' },
        { name: '', type: types[0], pk: false, notNull: false, def: '' },
    ];
}

// ─── validation ──────────────────────────────────────────────
// One list of human sentences, in the order an operator would fix them.
export function validate({ table, columns, unitOne = 'table' }) {
    const issues = [];
    const nameIssue = identError(table, `${unitOne.charAt(0).toUpperCase()}${unitOne.slice(1)} name`);
    if (nameIssue) issues.push(nameIssue);

    const named = columns.filter((c) => String(c.name || '').trim());
    if (!named.length) issues.push('Add at least one column.');

    named.forEach((c, i) => {
        const issue = identError(c.name, `Column ${i + 1} ("${String(c.name).trim()}")`);
        if (issue) issues.push(issue);
    });

    const seen = new Set();
    named.forEach((c) => {
        const key = String(c.name).trim().toLowerCase();
        if (seen.has(key)) issues.push(`Column "${String(c.name).trim()}" is listed twice.`);
        seen.add(key);
    });

    if (named.filter((c) => c.pk).length > 1) issues.push('Only one column can be the primary key.');

    return issues;
}

// ─── CREATE TABLE ────────────────────────────────────────────
export function buildCreateTable({ conn, dialect, table, columns }) {
    const d = SQL_DIALECTS[dialect] || SQL_DIALECTS.sqlite;
    const q = (ident) => quoteIdent(conn || { dbType: dialect }, ident);
    const named = columns.filter((c) => String(c.name || '').trim());
    const pk = named.find((c) => c.pk);
    const name = String(table || '').trim();

    let inlinePk = false;
    const lines = named.map((col) => {
        const isPk = col === pk;
        const generated = isPk && d.integers.includes(col.type);

        let type = col.type;
        let tail = '';
        if (generated) {
            if (dialect === 'postgresql') {
                type = col.type === 'BIGINT' ? 'BIGSERIAL' : 'SERIAL';
            } else if (dialect === 'sqlite') {
                type = 'INTEGER';
                tail = ' PRIMARY KEY AUTOINCREMENT';
                inlinePk = true;
            } else {
                tail = ' AUTO_INCREMENT';
            }
        }

        // A generated key never carries a DEFAULT. PostgreSQL's serial types and
        // SQLite's rowid alias are not-null by construction, so spelling it out
        // there only adds noise; MySQL's AUTO_INCREMENT is spelled out because
        // that is what its own dumps do.
        const impliedNotNull = generated && (dialect === 'postgresql' || dialect === 'sqlite');
        const notNull = !impliedNotNull && (col.notNull || isPk) ? ' NOT NULL' : '';
        const def = generated ? null : encodeDefault(dialect, col.def);
        const defaultSql = def ? ` DEFAULT ${def}` : '';

        return `  ${q(String(col.name).trim())} ${type}${notNull}${defaultSql}${tail}`;
    });

    if (pk && !inlinePk) lines.push(`  PRIMARY KEY (${q(String(pk.name).trim())})`);

    return `CREATE TABLE ${q(name || 'new_table')} (\n${lines.join(',\n') || '  …'}\n);`;
}

// ─── non-SQL families ────────────────────────────────────────
// The engines ServerKit can install but has no client bridge for. The shapes
// come from each engine's own client, so the operator can copy a statement that
// actually works rather than a SQL-flavoured guess.
const FAMILY_TYPES = {
    Document: ['String', 'Number', 'Boolean', 'Date', 'ObjectId', 'Array', 'Object'],
    Search: ['string', 'number', 'boolean', 'string[]'],
    'Time-series': ['field', 'tag', 'timestamp'],
    Graph: ['String', 'Integer', 'Float', 'Boolean', 'DateTime'],
    'Key-value': ['string', 'hash', 'list', 'set', 'zset'],
};

export function familyTypes(family) {
    return FAMILY_TYPES[family] || SQL_DIALECTS.postgresql.types;
}

export function familyHasTypes(family) {
    return Boolean(FAMILY_TYPES[family]);
}

const BSON_TYPES = {
    String: 'string', Number: 'double', Boolean: 'bool', Date: 'date',
    ObjectId: 'objectId', Array: 'array', Object: 'object',
};

// The word each family uses for "the thing you are creating" and for its key
// column, so the grid's headers speak the engine's language.
export function familyWording(family) {
    switch (family) {
        case 'Document': return { fields: 'Fields', key: 'Key', required: 'Required' };
        case 'Search': return { fields: 'Attributes', key: 'Primary', required: 'Searchable' };
        case 'Time-series': return { fields: 'Fields', key: 'Time', required: 'Required' };
        case 'Graph': return { fields: 'Properties', key: 'Unique', required: 'Required' };
        case 'Key-value': return { fields: 'Fields', key: 'Key', required: 'Required' };
        default: return { fields: 'Columns', key: 'PK', required: 'Not null' };
    }
}

// Generates the create statement in the engine's own client syntax. Copy-only:
// nothing in ServerKit can execute these today, which the modal says out loud.
export function buildFamilyStatement({ family, name, database, fields }) {
    const nm = String(name || '').trim() || 'new_collection';
    const db = String(database || '').trim() || '<database>';
    const named = fields.filter((f) => String(f.name || '').trim());
    const key = named.find((f) => f.pk);
    const list = (fn, sep = ', ') => named.map(fn).join(sep);

    switch (family) {
        case 'Document': {
            const required = named.filter((f) => f.notNull).map((f) => `"${String(f.name).trim()}"`).join(', ');
            const props = list((f) => `      ${String(f.name).trim()}: { bsonType: "${BSON_TYPES[f.type] || 'string'}" }`, ',\n') || '      …';
            const index = key ? `\ndb.${nm}.createIndex({ ${String(key.name).trim()}: 1 }, { unique: true })` : '';
            return `use ${db}\ndb.createCollection("${nm}", {\n  validator: { $jsonSchema: {\n    required: [${required}],\n    properties: {\n${props}\n    }\n  }}\n})${index}`;
        }
        case 'Search': {
            const primary = key ? `, "primaryKey": "${String(key.name).trim()}"` : '';
            const searchable = named.filter((f) => f.notNull).map((f) => `"${String(f.name).trim()}"`).join(', ')
                || list((f) => `"${String(f.name).trim()}"`);
            return `curl -X POST '/indexes' \\\n  -H 'Authorization: Bearer <master-key>' \\\n  -d '{ "uid": "${nm}"${primary} }'\n\ncurl -X PATCH '/indexes/${nm}/settings' \\\n  -H 'Authorization: Bearer <master-key>' \\\n  -d '{ "searchableAttributes": [${searchable}] }'`;
        }
        case 'Time-series': {
            const tags = named.filter((f) => f.type === 'tag').map((f) => String(f.name).trim()).join(', ') || '—';
            const values = named.filter((f) => f.type !== 'tag').map((f) => String(f.name).trim()).join(', ') || '—';
            return `influx bucket create --name ${nm} --retention 90d\n\n# tags:   ${tags}\n# fields: ${values}`;
        }
        case 'Graph': {
            const unique = key ? String(key.name).trim() : 'id';
            const props = list((f) => String(f.name).trim()) || '…';
            return `CREATE CONSTRAINT ${nm}_key IF NOT EXISTS\n  FOR (n:${nm}) REQUIRE n.${unique} IS UNIQUE;\n\n// properties: ${props}`;
        }
        case 'Key-value': {
            const pairs = list((f) => `${String(f.name).trim()} "<${f.type}>"`, ' ') || '<field> "<value>"';
            return `# Redis-compatible engines create a key on first write\nHSET ${nm}:1 ${pairs}`;
        }
        default: {
            // A relational engine we can't reach — plain ANSI SQL, copy-only.
            const cols = named.map((f) => `  "${String(f.name).trim()}" ${f.type}${f.notNull ? ' NOT NULL' : ''}`).join(',\n') || '  …';
            const pk = key ? `,\n  PRIMARY KEY ("${String(key.name).trim()}")` : '';
            return `CREATE TABLE "${nm}" (\n${cols}${pk}\n);`;
        }
    }
}
