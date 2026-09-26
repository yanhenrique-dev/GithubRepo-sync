"""Contrato de fronteira entre o backend local e `static/app.js`.

Este módulo é o artefato canônico e o ÚNICO lugar onde o formato das respostas
HTTP é declarado. O OpenAPI servido em `/openapi.json` é derivado destes
modelos pelo FastAPI — nunca editado à mão. O snapshot versionado em
`static/contract/openapi.json` é conferido por `tests/test_contract.py`.

Design a partir do consumidor, não do armazenamento: o que está aqui é o que a
tela consegue observar. Nada de coluna de banco, nome de tabela ou classe
interna.

Observações de contrato que valem para quem consome
--------------------------------------------------
* `branch` nunca é nulo: `core.scanner` normaliza para ``"main"`` quando não há
  branch explícita. `branch_explicit` é o sinal confiável de que a branch foi
  **fixada pelo usuário** — `auto` mede outra coisa (se o owner/repo foi
  deduzido dos metadados em vez de vir do mapeamento salvo).
* `can_rollback` e `last_check` já vêm preenchidos em `/api/scan`, não só em
  `/api/check`.
* O caminho de erro por linha (`error` preenchido em `/api/check`) devolve o
  item **sem** nenhum campo remoto. Por isso todo campo de check tem
  `default=None`: serializar sem default quebraria justamente o caminho de
  erro, que é o que o usuário mais precisa ver.
* `update_zip_only` devolve `backup` como `Path`. O contrato converte para str
  no limite — sem isso o FastAPI responde 500 em toda atualização no modo ZIP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# itens
# ---------------------------------------------------------------------------


class ScannedItem(BaseModel):
    """Um item detectado em `/api/scan` (pasta extraída e/ou .zip)."""

    model_config = ConfigDict(extra="ignore")

    # identidade
    name: str = Field(description="Nome da pasta/zip como existe no disco.")
    mapped: bool = Field(description="Se já existe vínculo com um repositório do GitHub.")
    auto: bool = Field(description="Owner/repo deduzido dos metadados, não do mapeamento salvo.")
    branch: str = Field(description="Branch monitorada. 'main' quando não há branch explícita.")
    branch_explicit: bool = Field(description="True quando a branch foi fixada explicitamente no mapeamento.")

    # artefatos locais
    local_dir: str | None = Field(default=None, description="Pasta extraída, se existir.")
    zip_path: str | None = Field(default=None, description="Arquivo .zip, se existir.")

    # vínculo com o GitHub
    github_url: str | None = Field(default=None)
    owner: str | None = Field(default=None)
    repo: str | None = Field(default=None)
    suggested_repo: str | None = Field(default=None, description="Palpite de nome quando ainda não há vínculo.")
    tried: list[str] | None = Field(default=None, description="Tentativas de detecção que falharam.")

    # estado local
    local_sha: str | None = Field(default=None, description="SHA do artefato em uso, se registrado.")
    can_rollback: bool = Field(default=False, description="Existe backup .bak para reverter.")
    last_check: str | None = Field(default=None, description="ISO 8601 da última consulta ao GitHub.")


class CheckedItem(ScannedItem):
    """Um item de `/api/check`: acrescenta o que veio do GitHub."""

    behind: bool | None = Field(
        default=None,
        description="True=atualização disponível, False=em dia, None=artefato ausente ou erro.",
    )
    error: str | None = Field(default=None, description="Erro desta linha; as demais linhas não são afetadas.")
    remote_sha: str | None = None
    remote_date: str | None = None
    remote_message: str | None = None
    release_tag: str | None = None
    source: str | None = None
    zipball_url: str | None = None
    canonical_url: str | None = None


# ---------------------------------------------------------------------------
# respostas
# ---------------------------------------------------------------------------


class ScanResponse(BaseModel):
    path: str
    items: list[ScannedItem]
    zip_only: bool
    backup: bool


class CheckResponse(BaseModel):
    path: str
    items: list[CheckedItem]


class UpdateResponse(BaseModel):
    ok: bool
    name: str
    remote_sha: str
    zip_only: bool
    path: str
    backup: bool | str | None = None
    old_bytes: int | None = None
    new_bytes: int | None = None
    download_bytes: int | None = None
    speed_bps: float | None = None

    @field_validator("backup", "path", mode="before")
    @classmethod
    def _str_paths(cls, value: Any) -> Any:
        """`core.updater` devolve Path; o contrato entrega str."""
        return str(value) if isinstance(value, Path) else value


class RollbackResponse(BaseModel):
    ok: bool
    name: str
    restored_from: str
    path: str
    zip_only: bool

    @field_validator("restored_from", "path", mode="before")
    @classmethod
    def _str_paths(cls, value: Any) -> Any:
        return str(value) if isinstance(value, Path) else value


class TokenStatus(BaseModel):
    """Nunca expõe o token: só presença, validade e cota."""

    configured: bool
    valid: bool | None = None
    remaining: int | None = None
    limit: int | None = None
    rate_limited: bool = False


class Suggestion(BaseModel):
    full_name: str | None = None
    url: str | None = None
    stars: int = 0
    description: str | None = None


class SuggestResponse(BaseModel):
    items: list[Suggestion]


class LogResponse(BaseModel):
    lines: list[str]


class HealthResponse(BaseModel):
    ok: bool
    service: str


class OkResponse(BaseModel):
    """Resposta das rotas que só confirmam: `/api/map`."""

    ok: bool


class FlagResponse(BaseModel):
    """Resposta de `/api/mode` e `/api/backup`: confirma e devolve a flag."""

    ok: bool
    zip_only: bool | None = None
    backup: bool | None = None


# ---------------------------------------------------------------------------
# esquema de item, derivado dos modelos
# ---------------------------------------------------------------------------


def _describe(model: type[BaseModel]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, spec in model.model_fields.items():
        entry: dict[str, Any] = {
            "type": "string" if spec.annotation is str else "other",
            "required": spec.is_required(),
        }
        if not spec.is_required():
            entry["optional"] = True
            entry["default"] = None if spec.get_default(call_default_factory=True) is None else "set"
        if spec.description:
            entry["description"] = spec.description
        out[name] = entry
    return out


#: Campos de item que `static/app.js` pode ler. Deriva de `CheckedItem`, que
#: herda de `ScannedItem` — logo cresce junto com o contrato.
ITEM_SCHEMA: dict[str, dict[str, Any]] = _describe(CheckedItem)

#: Campos de topo que `static/app.js` lê de cada resposta.
TOP_LEVEL_SCHEMA: dict[str, dict[str, dict[str, Any]]] = {
    "scan": _describe(ScanResponse),
    "check": _describe(CheckResponse),
    "update": _describe(UpdateResponse),
    "rollback": _describe(RollbackResponse),
    "token": _describe(TokenStatus),
    "log": _describe(LogResponse),
    "health": _describe(HealthResponse),
    "suggest": _describe(SuggestResponse),
    "map": _describe(OkResponse),
    "flag": _describe(FlagResponse),
}
