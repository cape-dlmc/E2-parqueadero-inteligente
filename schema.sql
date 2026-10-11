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
