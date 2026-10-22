from pathlib import Path
import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENPLAYOUT_", env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    ffprobe: str = "ffprobe"
    caspar_host: str = "127.0.0.1"
    caspar_port: int = 5250
    caspar_media_root: str = str(ROOT / "media")
    caspar_autostart: bool = True
    caspar_server_dir: Path = ROOT / ".tools" / "casparcg" / "2.5.1"
    caspar_start_timeout: float = 45
    caspar_screen: bool = True
    scheduler_lateness_seconds: float = Field(default=0.5, gt=0, le=10, allow_inf_nan=False)
    graphics_base_url: str = "http://127.0.0.1:8000"
    trusted_plugins: list[str] = Field(default_factory=list)
    origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000"
    api_token: str = ""

    def prepare(self) -> None:
        self.data_dir = self.data_dir.resolve()
        self.caspar_media_root = str(Path(self.caspar_media_root).resolve())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.api_token:
            path = self.data_dir / "api-token"
            if not path.exists():
                path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            self.api_token = path.read_text(encoding="utf-8").strip()
        if len(self.api_token) < 24:
            raise ValueError("API token must contain at least 24 characters")

    @property
    def allowed_origins(self) -> list[str]:
        return [value.strip() for value in self.origins.split(",") if value.strip()]
