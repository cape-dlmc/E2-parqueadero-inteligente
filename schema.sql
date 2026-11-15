-- Esquema del sistema (heredado de E1). Es idempotente: se puede aplicar varias veces.
CREATE TABLE IF NOT EXISTS zona (
    codigo_zona TEXT PRIMARY KEY,
    capacidad   INTEGER NOT NULL CHECK (capacidad > 0)
);

CREATE TABLE IF NOT EXISTS lectura_ocupacion (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_zona TEXT NOT NULL,
    fecha_hora  TEXT NOT NULL,
    ocupacion   INTEGER NOT NULL CHECK (ocupacion >= 0),
    FOREIGN KEY (codigo_zona) REFERENCES zona(codigo_zona),
    UNIQUE (codigo_zona, fecha_hora)
);

CREATE INDEX IF NOT EXISTS idx_lectura_fecha ON lectura_ocupacion(fecha_hora);

CREATE TRIGGER IF NOT EXISTS trg_ocupacion_no_supera_capacidad
BEFORE INSERT ON lectura_ocupacion
FOR EACH ROW
WHEN NEW.ocupacion > (SELECT capacidad FROM zona WHERE codigo_zona = NEW.codigo_zona)
BEGIN
    SELECT RAISE(ABORT, 'OCUPACION_SUPERA_CAPACIDAD');
END;

-- ==========================================================================
-- E2 · Sedes, ubicación, restricciones por zona y reservas
-- ==========================================================================
CREATE TABLE IF NOT EXISTS sede (
    id           INTEGER PRIMARY KEY,
    nombre       TEXT NOT NULL,
    ciudad       TEXT NOT NULL,
    departamento TEXT NOT NULL,
    latitud      REAL NOT NULL,
    longitud     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS zona_ubicacion (
    codigo_zona TEXT PRIMARY KEY,
    sede_id     INTEGER NOT NULL,
    nombre      TEXT NOT NULL,
    sector      TEXT NOT NULL,
    x           INTEGER NOT NULL CHECK (x BETWEEN 0 AND 100),
    y           INTEGER NOT NULL CHECK (y BETWEEN 0 AND 100),
    FOREIGN KEY (codigo_zona) REFERENCES zona(codigo_zona),
    FOREIGN KEY (sede_id) REFERENCES sede(id)
);

CREATE TABLE IF NOT EXISTS restriccion_zona (
    codigo_zona                  TEXT PRIMARY KEY,
    reservable                   INTEGER NOT NULL DEFAULT 1 CHECK (reservable IN (0, 1)),
    tipos_permitidos             TEXT NOT NULL DEFAULT 'carro,moto',
    hora_apertura                TEXT NOT NULL DEFAULT '06:00',
    hora_cierre                  TEXT NOT NULL DEFAULT '22:00',
    max_horas_reserva            INTEGER NOT NULL DEFAULT 8 CHECK (max_horas_reserva BETWEEN 1 AND 24),
    max_reservas_activas_usuario INTEGER NOT NULL DEFAULT 2 CHECK (max_reservas_activas_usuario >= 1),
    nota                         TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (codigo_zona) REFERENCES zona(codigo_zona)
);

CREATE TABLE IF NOT EXISTS usuario (
    identificacion TEXT PRIMARY KEY,
    nombre         TEXT NOT NULL,
    tipo_vehiculo  TEXT NOT NULL CHECK (tipo_vehiculo IN ('carro', 'moto')),
    placa          TEXT NOT NULL DEFAULT '',
    clave_hash     TEXT NOT NULL DEFAULT ''   -- PBKDF2-SHA256 con sal; nunca texto plano
);

CREATE TABLE IF NOT EXISTS reserva (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_zona    TEXT NOT NULL,
    identificacion TEXT NOT NULL,
    inicio         TEXT NOT NULL,
    fin            TEXT NOT NULL,
    estado         TEXT NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'cancelada')),
    creada_en      TEXT NOT NULL,
    CHECK (inicio < fin),
    FOREIGN KEY (codigo_zona) REFERENCES zona(codigo_zona),
    FOREIGN KEY (identificacion) REFERENCES usuario(identificacion)
);

CREATE INDEX IF NOT EXISTS idx_reserva_zona ON reserva(codigo_zona, estado, inicio, fin);
CREATE INDEX IF NOT EXISTS idx_reserva_usuario ON reserva(identificacion, estado);
