"""SimCity 2013 Mod Manager — local Flask application, no launcher/DRM integration."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import requests
from flask import Flask, abort, jsonify, render_template, request, session

BASE = Path(__file__).resolve().parent
RUNTIME = BASE / ".runtime"
RUNTIME.mkdir(exist_ok=True)
CONFIG_FILE = RUNTIME / "config.json"
STATE_FILE = RUNTIME / "state.json"
SECRET_FILE = RUNTIME / "secret.key"
CATALOG = json.loads((BASE / "catalog.json").read_text(encoding="utf-8"))
CAT_BY_ID = {m["id"]: m for m in CATALOG}
MAX_ARCHIVE = 180 * 1024 * 1024
MAX_ITEM = 80 * 1024 * 1024
MAX_TOTAL = 260 * 1024 * 1024
MAX_FILES = 100
MUTEX = threading.RLock()
JOBS: dict[str, dict] = {}
log = logging.getLogger("sc13-manager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

if not SECRET_FILE.exists():
    SECRET_FILE.write_bytes(secrets.token_bytes(32))
app = Flask(__name__)
app.secret_key = SECRET_FILE.read_bytes()
app.config["MAX_CONTENT_LENGTH"] = MAX_ARCHIVE + (2 * 1024 * 1024)
app.json.ensure_ascii = False

def load_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default.copy()
    except (OSError, ValueError):
        return default.copy()

def save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False, suffix=".tmp") as temp:
        json.dump(obj, temp, ensure_ascii=False, indent=2)
        temp_path = Path(temp.name)
    os.replace(temp_path, path)

def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def game_root() -> Path | None:
    config = load_json(CONFIG_FILE, {})
    configured = os.environ.get("SIMCITY_PATH") or config.get("game_path")
    candidates = ([configured] if configured else []) + [
        r"E:\GOG Games\SimCity 2013",
        r"E:\GOG Games\SimCity",
        r"E:\Games\SimCity 2013",
        r"C:\Program Files (x86)\Origin Games\SimCity",
        r"C:\Program Files\EA Games\SimCity",
        r"C:\Program Files (x86)\EA Games\SimCity",
        r"D:\Games\SimCity",
    ]
    for option in candidates:
        if not option:
            continue
        p = Path(option).expanduser()
        if p.name.lower() == "simcitydata":
            p = p.parent
        if valid_game(p):
            return p.resolve()
    return None

def valid_game(path: Path) -> bool:
    try:
        if "simcity 4" in str(path).lower() or "simcity4" in str(path).lower():
            return False
        folder = path / "SimCityData"
        return folder.is_dir() and any(folder.glob("*.package"))
    except OSError:
        return False

def require_game() -> Path:
    root = game_root()
    if root is None:
        raise ValueError("Pasta do SimCity (2013) não configurada ou inválida. Selecione o diretório que contém SimCityData.")
    return root

def paths_for(root: Path) -> dict:
    return {
        "SimCityData": root / "SimCityData",
        "SimCityUserData/Packages": root / "SimCityUserData" / "Packages",
    }

def safe_target(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or len(rel.parts) < 2:
        raise ValueError("Caminho armazenado inválido.")
    target = (root / Path(*rel.parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Destino fora do diretório do jogo.")
    return target

def is_game_file(filename: str) -> bool:
    value = filename.casefold()
    return (
        value.startswith(("simcity_game_", "simcity_audio_", "simcitydlcep1_", "simcity-scripts_",
                          "simcitydlcep1-scripts_", "simcity_region_", "simcity_ui_"))
        or value in {"simcitydata.package", "simcitydataep1.package", "simcity_game.package", "simcity_game_data.package", "simcity_app.package", "simcity_graphics.package", "simcity_dlc0.package", "simcity_regionterrain0.package", "simcity_regionterrain1.package", "patch.package"}
    )

def mod_matches(filename: str, entry: dict) -> bool:
    name = filename.casefold()
    return any(pattern.casefold() in name for pattern in entry.get("patterns", []))

def scan(root: Path | None) -> tuple[list[dict], list[dict]]:
    inventory: list[dict] = []
    known = load_json(STATE_FILE, {"managed": {}, "history": []}).get("managed", {})
    managed_paths = {
        f.get("path", "").casefold(): mod_id
        for mod_id, record in known.items()
        for f in record.get("files", [])
    }
    if root:
        for folder_key, folder in paths_for(root).items():
            if not folder.is_dir():
                continue
            for p in sorted(folder.rglob("*.package"), key=lambda x: x.name.casefold()):
                if not p.is_file() or len(inventory) >= 3000:
                    continue
                try:
                    relative = p.relative_to(root).as_posix()
                    entry = next((m for m in CATALOG if mod_matches(p.name, m)), None)
                    owner = managed_paths.get(relative.casefold())
                    game = is_game_file(p.name) and not owner
                    inventory.append({
                        "name": p.name, "path": relative, "bytes": p.stat().st_size,
                        "kind": "jogo" if game else ("gerenciado" if owner else "externo"),
                        "category": entry["category"] if entry else ("Sistema" if game else "Não catalogado"),
                        "catalog_id": entry["id"] if entry else None,
                        "managed": bool(owner),
                    })
                except OSError:
                    continue
    mods: list[dict] = []
    for item in CATALOG:
        match = [p for p in inventory if not (p["kind"] == "jogo") and mod_matches(p["name"], item)]
        managed = item["id"] in known
        mods.append({
            **item, "installed": bool(match) or managed,
            "managed": managed,
            "files": [p["name"] for p in match],
            "detected": bool(match),
            "auto_available": bool(item.get("direct_url")) and not item.get("complex"),
        })
    return inventory, mods

def stats() -> dict:
    root = game_root()
    inventory, mods = scan(root)
    custom = [p for p in inventory if p["kind"] != "jogo"]
    cats = dict(Counter(p["category"] for p in custom))
    state = load_json(STATE_FILE, {"managed": {}, "history": []})
    return {
        "ready": root is not None,
        "game_path": str(root) if root else (os.environ.get("SIMCITY_PATH") or load_json(CONFIG_FILE, {}).get("game_path", "")),
        "targets": {k: str(v) for k, v in paths_for(root).items()} if root else {},
        "inventory": custom,
        "mods": mods,
        "history": state.get("history", [])[-50:],
        "categories": cats,
        "kpi": {
            "files": len(custom),
            "catalog_installed": sum(1 for m in mods if m["installed"]),
            "catalog_total": len(mods),
            "managed": len(state.get("managed", {})),
            "bytes": sum(p["bytes"] for p in custom),
            "system_files": len(inventory) - len(custom),
        },
    }

def validate_archive_name(name: str) -> bool:
    norm = name.replace("\\", "/")
    p = PurePosixPath(norm)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and ":" not in p.parts[0] and p.suffix.lower() == ".package"

def validate_package(name: str, payload: bytes) -> None:
    if not validate_archive_name(name):
        raise ValueError("Nome de arquivo inseguro ou tipo diferente de .package.")
    if is_game_file(Path(name).name):
        raise ValueError("Arquivo original de jogo/script detectado; não será substituído.")
    if len(payload) < 8 or not payload.startswith(b"DBPF"):
        raise ValueError("Arquivo .package inválido: cabeçalho DBPF ausente.")
    if len(payload) > MAX_ITEM:
        raise ValueError("Pacote individual maior que o limite de 80 MB.")

def packages_from_file(archive: Path) -> list[tuple[str, bytes]]:
    header = archive.read_bytes()[:8]
    packages: list[tuple[str, bytes]] = []
    total = 0

    def add(name: str, content: bytes) -> None:
        nonlocal total
        if not validate_archive_name(name):
            return
        if len(packages) >= MAX_FILES:
            raise ValueError("Arquivo contém pacotes demais.")
        total += len(content)
        if total > MAX_TOTAL:
            raise ValueError("Arquivo excede 260 MB de dados extraídos.")
        filename = Path(name.replace("\\", "/")).name
        validate_package(filename, content)
        if any(prev_name.casefold() == filename.casefold() for prev_name, _ in packages):
            raise ValueError("Arquivos .package de nomes repetidos no mesmo pacote.")
        packages.append((filename, content))

    if header.startswith(b"DBPF"):
        add(archive.name if archive.suffix.lower() == ".package" else "mod.package", archive.read_bytes())
    elif zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            members = [n for n in zf.infolist() if validate_archive_name(n.filename) and not n.is_dir()]
            if len(members) > MAX_FILES or sum(n.file_size for n in members) > MAX_TOTAL:
                raise ValueError("Compactado excede limite de arquivos ou tamanho.")
            for member in members:
                if member.file_size > MAX_ITEM:
                    raise ValueError("Pacote interno excede limite de tamanho.")
                add(member.filename, zf.read(member))
    elif header.startswith(b"7z\xbc\xaf\x27\x1c"):
        try:
            import py7zr
        except ImportError as exc:
            raise ValueError("Instale py7zr para arquivos .7z.") from exc
        with tempfile.TemporaryDirectory() as temp:
            with py7zr.SevenZipFile(archive, mode="r") as zf:
                names = [n for n in zf.getnames() if validate_archive_name(n)]
                if len(names) > MAX_FILES:
                    raise ValueError("Muitos arquivos no .7z.")
                zf.extract(path=temp, targets=names)
            for name in names:
                p = (Path(temp) / Path(*PurePosixPath(name.replace("\\", "/")).parts)).resolve()
                if not p.is_relative_to(Path(temp).resolve()) or not p.is_file():
                    raise ValueError("Caminho inseguro no arquivo .7z.")
                if p.stat().st_size > MAX_ITEM:
                    raise ValueError("Pacote interno excede limite de tamanho.")
                add(name, p.read_bytes())
    elif header.startswith(b"Rar!\x1a\x07"):
        try:
            import rarfile
            with rarfile.RarFile(archive) as rf:
                members = [n for n in rf.infolist() if validate_archive_name(n.filename) and not n.isdir()]
                if len(members) > MAX_FILES or sum(n.file_size for n in members) > MAX_TOTAL:
                    raise ValueError("Arquivo RAR excede limite de arquivos ou tamanho.")
                for member in members:
                    if member.file_size > MAX_ITEM:
                        raise ValueError("Pacote interno excede limite de tamanho.")
                    add(member.filename, rf.read(member))
        except (ImportError, OSError) as exc:
            raise ValueError("Falha ao ler RAR. Instale 7-Zip e disponibilize 7z.exe no PATH.") from exc
    else:
        raise ValueError("Formato inválido. Envie .package, .zip, .7z ou .rar com arquivos .package.")
    if not packages:
        raise ValueError("Nenhum .package válido encontrado no arquivo.")
    return packages

def install_packages(mod: dict, items: list[tuple[str, bytes]]) -> dict:
    if mod.get("complex"):
        raise ValueError("Este pacote requer instalação guiada, seleção de componentes ou scripts. Consulte o autor.")
    if mod.get("single_variant") and len(items) != 1:
        raise ValueError("Este mod exige uma única variante de câmera. Envie somente o .package escolhido.")
    with MUTEX:
        root = require_game()
        state = load_json(STATE_FILE, {"managed": {}, "history": []})
        if mod["id"] in state.get("managed", {}):
            raise ValueError("Mod já gerenciado. Remova pelo painel antes de reinstalar.")
        folder_name = mod.get("install_to", "SimCityData")
        target_root = paths_for(root).get(folder_name)
        if not target_root:
            raise ValueError("Destino do mod não permitido.")
        planned: list[tuple[Path, bytes]] = []
        for name, data in items:
            validate_package(name, data)
            target = target_root / name
            if target.exists():
                raise ValueError("O arquivo " + name + " já existe. Remova-o manualmente ou faça backup antes.")
            if any(mod_matches(name, other) for other in CATALOG if other["id"] != mod["id"] and
                   (other.get("complex") or other.get("level") == "alto")):
                log.warning("Arquivo pode pertencer a outro pacote: %s", name)
            planned.append((target, data))
        installed: list[dict] = []
        try:
            target_root.mkdir(parents=True, exist_ok=True)
            for target, data in planned:
                with tempfile.NamedTemporaryFile(dir=target_root, delete=False, suffix=".tmp") as tmp:
                    tmp.write(data)
                    tmp_path = Path(tmp.name)
                try:
                    os.replace(tmp_path, target)
                finally:
                    tmp_path.unlink(missing_ok=True)
                installed.append({
                    "path": target.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                })
        except Exception:
            for record in installed:
                safe_target(root, record["path"]).unlink(missing_ok=True)
            raise
        state.setdefault("managed", {})[mod["id"]] = {"files": installed, "installed_at": now()}
        state.setdefault("history", []).append({"at": now(), "event": "install", "mod": mod["name"]})
        save_json(STATE_FILE, state)
    log.info("INSTALADO %s: %s", mod["name"], ", ".join(p["path"] for p in installed))
    return {"installed": len(installed), "files": [f["path"] for f in installed]}

def delete_managed(mod_id: str) -> dict:
    with MUTEX:
        root = require_game()
        state = load_json(STATE_FILE, {"managed": {}, "history": []})
        record = state.get("managed", {}).get(mod_id)
        if not record:
            raise ValueError("Mod não foi instalado por este gerenciador. Remoção manual necessária.")
        paths = []
        for item in record.get("files", []):
            target = safe_target(root, item["path"])
            if target.exists() and sha256(target) != item["sha256"]:
                raise ValueError("Arquivo alterado após instalação: " + target.name + ". Remoção cancelada.")
            paths.append(target)
        for p in paths:
            p.unlink(missing_ok=True)
        del state["managed"][mod_id]
        state.setdefault("history", []).append({"at": now(), "event": "remove", "mod": CAT_BY_ID[mod_id]["name"]})
        save_json(STATE_FILE, state)
    log.info("REMOVIDO: %s", mod_id)
    return {"removed": len(paths)}

def local_source(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in {"community.simtropolis.com", "simtropolis.com"}

def update_job(job: str, **kwargs) -> None:
    with MUTEX:
        JOBS[job].update(kwargs)

def download_worker(job: str, mod: dict) -> None:
    url = mod.get("direct_url") or mod["source"].rstrip("/") + "/?do=download"
    try:
        if not local_source(url):
            raise ValueError("Fonte automática não autorizada.")
        update_job(job, status="downloading", message="Tentando baixar do Simtropolis…")
        log.info("DOWNLOAD %s: %s", mod["name"], url)
        with requests.get(url, stream=True, timeout=(12, 45), headers={"User-Agent": "SimCity2013-ModManager/1.0"}) as response:
            response.raise_for_status()
            if response.url.startswith("http://"):
                raise ValueError("Redirecionamento sem HTTPS bloqueado.")
            with tempfile.TemporaryDirectory() as td:
                temp = Path(td) / "download.bin"
                size = 0
                with temp.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            size += len(chunk)
                            if size > MAX_ARCHIVE:
                                raise ValueError("Download excedeu 180 MB.")
                            out.write(chunk)
                            update_job(job, bytes=size)
                with temp.open("rb") as f:
                    magic = f.read(8)
                if not (magic.startswith((b"DBPF", b"PK\x03\x04", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c"))):
                    raise ValueError("Fonte exige login, seleção de download ou devolveu HTML.")
                if magic.startswith(b"DBPF"):
                    disposition = response.headers.get("Content-Disposition", "")
                    match = re.search(r'filename="?([^";]+)', disposition, flags=re.IGNORECASE)
                    original_name = Path(match.group(1).replace("\\", "/")).name if match else ""
                    package_name = original_name if original_name.lower().endswith(".package") else "000_" + mod["id"] + ".package"
                    package_file = Path(td) / package_name
                    temp.rename(package_file)
                    temp = package_file
                payloads = packages_from_file(temp)
                result = install_packages(mod, payloads)
                update_job(job, status="done", message="Download e instalação concluídos.", result=result)
    except Exception as exc:
        log.warning("DOWNLOAD MANUAL NECESSÁRIO %s: %s", mod["name"], exc)
        update_job(job, status="manual", message=str(exc) + " Abra a fonte e importe o arquivo pelo painel.", source=mod["source"])

@app.before_request
def csrf_protection() -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not hmac.compare_digest(token, session.get("csrf", "")):
            abort(403)

@app.get("/")
def index():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(24)
    return render_template("index.html", csrf=session["csrf"])

@app.get("/api/summary")
def summary():
    return jsonify(stats())

@app.post("/api/config")
def configure():
    path = str((request.get_json(silent=True) or {}).get("game_path", "")).strip().strip('"')
    if not path or len(path) > 512:
        return jsonify(error="Informe um caminho válido."), 400
    resolved = Path(path).expanduser()
    if resolved.name.casefold() == "simcitydata":
        resolved = resolved.parent
    if not valid_game(resolved):
        return jsonify(error="Pasta inválida: selecione a raiz do SimCity (2013), contendo SimCityData com arquivos .package. SimCity 4 não é aceito."), 400
    if os.environ.get("SIMCITY_PATH"):
        return jsonify(error="O caminho está definido pela variável SIMCITY_PATH. Altere a variável e reinicie."), 409
    save_json(CONFIG_FILE, {"game_path": str(resolved.resolve())})
    log.info("JOGO CONFIGURADO: %s", resolved)
    return jsonify(ok=True, game_path=str(resolved.resolve()))

@app.post("/api/install/<mod_id>/upload")
def upload(mod_id: str):
    mod = CAT_BY_ID.get(mod_id)
    if not mod:
        abort(404)
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Selecione um arquivo de mod."), 400
    if Path(file.filename).suffix.casefold() not in {".package", ".zip", ".rar", ".7z"}:
        return jsonify(error="Extensão não permitida."), 400
    try:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / Path(file.filename.replace("\\", "/")).name
            file.save(target)
            result = install_packages(mod, packages_from_file(target))
        return jsonify(ok=True, result=result)
    except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        log.warning("IMPORTAÇÃO FALHOU %s: %s", mod_id, exc)
        return jsonify(error=str(exc)), 400

@app.post("/api/install/<mod_id>/download")
def download(mod_id: str):
    mod = CAT_BY_ID.get(mod_id)
    if not mod:
        abort(404)
    if mod.get("complex"):
        return jsonify(error="Pacote complexo: use as instruções do autor. Instalação automática indisponível.", source=mod["source"]), 400
    try:
        require_game()
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    job = uuid.uuid4().hex
    with MUTEX:
        JOBS[job] = {"status": "queued", "message": "Aguardando download.", "bytes": 0,
                     "name": mod["name"], "source": mod["source"], "created": now()}
    threading.Thread(target=download_worker, args=(job, mod), daemon=True).start()
    return jsonify(ok=True, job_id=job), 202

@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    with MUTEX:
        job = JOBS.get(job_id)
        return jsonify(job) if job is not None else (jsonify(error="Tarefa inexistente."), 404)

@app.post("/api/uninstall/<mod_id>")
def uninstall(mod_id: str):
    if mod_id not in CAT_BY_ID:
        abort(404)
    try:
        return jsonify(ok=True, result=delete_managed(mod_id))
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400

@app.get("/api/health")
def health():
    return jsonify(ok=True, game_detected=game_root() is not None)

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Arquivo maior que o limite de 180 MB."), 413

@app.errorhandler(403)
def forbidden(_):
    return jsonify(error="Sessão expirada; atualize a página."), 403

if __name__ == "__main__":
    log.info("SimCity 2013 Mod Manager iniciado em http://127.0.0.1:5000")
    log.info("Arquivo do jogo: %s", game_root() or "ainda não configurado")
    log.info("Mods suportados no catálogo: %s", len(CATALOG))
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False, threaded=True)
