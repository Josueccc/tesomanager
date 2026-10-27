from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://teso:teso@localhost:5432/tesomanager"
    secret_key: str = "cambia-esta-clave"

    # Usuario tesorero inicial (seed)
    admin_email: str = "tesorero@iglesia.local"
    admin_password: str = "cambiar123"
    admin_nombre: str = "Tesorero"

    moneda: str = "MXN"


settings = Settings()
