"""SQLite adapter for the launch-intent port, on the journal's own worker."""
from .models import CoreError, SessionKey
from .process_launch import (ProcessLaunchIdentity, ProcessLaunchRecord,
                             transition_launch, validate_launch_identity)


PROCESS_LAUNCH_SCHEMA = '''
CREATE TABLE IF NOT EXISTS process_launches (
    server_id TEXT NOT NULL,
    executor_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    opening_operation_id TEXT NOT NULL,
    connection_generation INTEGER NOT NULL,
    owner_generation INTEGER NOT NULL,
    platform TEXT NOT NULL,
    containment TEXT NOT NULL,
    container_id TEXT NOT NULL UNIQUE,
    producer_id TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL CHECK(schema_version=1),
    revision INTEGER NOT NULL CHECK(revision>=1),
    spawn_claimed INTEGER NOT NULL CHECK(spawn_claimed IN (0,1)),
    producer_fenced INTEGER NOT NULL CHECK(producer_fenced IN (0,1)),
    stop_proof TEXT CHECK(stop_proof IN ('NEVER_CLAIMED','CONTAINER_STOPPED')),
    PRIMARY KEY(server_id,executor_id,session_id),
    CHECK(stop_proof IS NULL OR producer_fenced=1),
    CHECK(stop_proof IS NULL OR stop_proof<>'NEVER_CLAIMED' OR spawn_claimed=0)
);
CREATE INDEX IF NOT EXISTS pending_process_launches ON process_launches(stop_proof);
'''


def _namespace(key):
    if not isinstance(key, SessionKey):
        raise ValueError('Invalid process launch session')
    return key.server_id, key.executor_id, key.session_id


def _read(db, key):
    row = db.execute('SELECT opening_operation_id,connection_generation,owner_generation,'
        'platform,containment,container_id,producer_id,schema_version,revision,spawn_claimed,'
        'producer_fenced,stop_proof FROM process_launches '
        'WHERE server_id=? AND executor_id=? AND session_id=?', _namespace(key)).fetchone()
    if row is None:
        return None
    identity = ProcessLaunchIdentity(key, *row[:8])
    validate_launch_identity(identity)
    return ProcessLaunchRecord(identity, row[8], bool(row[9]), bool(row[10]), row[11])


class ProcessLaunchStorageMixin:
    async def prepare_process_launch(self, identity):
        validate_launch_identity(identity)
        def write(db):
            db.execute('BEGIN IMMEDIATE')
            try:
                old = _read(db, identity.key)
                if old is not None:
                    if old.identity != identity:
                        raise CoreError('PROCESS_LAUNCH_CONFLICT', 'process_launch')
                    db.execute('COMMIT')
                    return old
                key = _namespace(identity.key)
                claim = db.execute('SELECT c.operation_id,g.connection_generation,g.owner_generation '
                    'FROM session_claims c LEFT JOIN session_open_generations g '
                    'ON g.server_id=c.server_id AND g.executor_id=c.executor_id AND g.session_id=c.session_id '
                    'AND g.operation_id=c.operation_id WHERE c.server_id=? AND c.executor_id=? AND c.session_id=?', key).fetchone()
                if claim is None:
                    raise CoreError('SESSION_UNKNOWN', 'process_launch')
                if tuple(claim) != (identity.opening_operation_id, identity.connection_generation, identity.owner_generation):
                    raise CoreError('PROCESS_LAUNCH_CONFLICT', 'process_launch')
                operation = db.execute('SELECT possible_effect,stage FROM operations_v2 WHERE '
                    'server_id=? AND executor_id=? AND operation_id=?',
                    (*key[:2], identity.opening_operation_id)).fetchone()
                if operation is None or not operation[0] or operation[1] != 'SUBMISSION_STARTED':
                    raise CoreError('PROCESS_LAUNCH_NOT_ADMITTED', 'process_launch')
                if db.execute('SELECT 1 FROM process_births WHERE server_id=? AND executor_id=? AND session_id=?', key).fetchone():
                    raise CoreError('PROCESS_LAUNCH_TOO_LATE', 'process_launch')
                self._require_storage_capacity(db, 1024, critical=True, stage='process_launch',
                    possible_effect=True, operation_id=identity.opening_operation_id)
                db.execute('INSERT INTO process_launches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (*key, identity.opening_operation_id, identity.connection_generation, identity.owner_generation,
                     identity.platform, identity.containment, identity.container_id, identity.producer_id,
                     identity.schema_version, 1, 0, 0, None))
                db.execute('COMMIT')
                return ProcessLaunchRecord(identity)
            except BaseException as error:
                self._rollback_if_active(db)
                from .journal import _sqlite_full
                if _sqlite_full(error):
                    raise CoreError('JOURNAL_FULL', 'process_launch', possible_effect=True,
                                    operation_id=identity.opening_operation_id) from error
                raise
        return await self._run(write, urgent=False)

    async def get_process_launch(self, session):
        _namespace(session)
        return await self._run(lambda db: _read(db, session), urgent=False)

    async def transition_process_launch(self, identity, *, expected_revision, action, stop_proof=None):
        validate_launch_identity(identity)
        def write(db):
            db.execute('BEGIN IMMEDIATE')
            try:
                old = _read(db, identity.key)
                if old is None:
                    raise CoreError('PROCESS_LAUNCH_UNKNOWN', 'process_launch')
                if old.identity != identity:
                    raise CoreError('PROCESS_LAUNCH_CONFLICT', 'process_launch')
                updated = transition_launch(old, expected_revision=expected_revision,
                                            action=action, stop_proof=stop_proof)
                if updated != old:
                    db.execute('UPDATE process_launches SET revision=?,spawn_claimed=?,producer_fenced=?,stop_proof=? '
                        'WHERE server_id=? AND executor_id=? AND session_id=? AND revision=?',
                        (updated.revision, int(updated.spawn_claimed), int(updated.producer_fenced), updated.stop_proof,
                         *_namespace(identity.key), old.revision))
                db.execute('COMMIT')
                return updated
            except BaseException as error:
                self._rollback_if_active(db)
                from .journal import _sqlite_full
                if _sqlite_full(error):
                    raise CoreError('JOURNAL_FULL', 'process_launch', possible_effect=True,
                                    operation_id=identity.opening_operation_id) from error
                raise
        return await self._run(write, urgent=True)

    @staticmethod
    def _validate_launch_birth(db, session, evidence):
        launch = _read(db, session)
        if launch is None:
            return  # Existing M1 evidence stays valid; absence is not stop proof.
        identity = launch.identity
        if (not launch.spawn_claimed or (evidence.platform, evidence.containment, evidence.container_id) !=
                (identity.platform, identity.containment, identity.container_id)):
            raise CoreError('PROCESS_BIRTH_CONFLICT', 'process_birth')
