from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pdfplumber


ROOT = Path(__file__).resolve().parent
SAMPLE_PDF = Path(
    r"C:\Users\cotiz\Fentexhaus Dropbox\Jose Juan Garza\HTF\Diego Jimenez\LT 585 Diego Jimenez HT10\HTF LT 585 Diego Jimenez HT10 - copia.pdf"
)


def content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".ico":
        return "image/x-icon"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript; charset=utf-8"
    return "application/octet-stream"

LEAF_PROFILE_CATALOG = [
    {"system": "Kömmerling 76 AD", "profile": "76201", "description": "Hoja interior de 78"},
    {"system": "Kömmerling 76 AD", "profile": "76204", "description": "Hoja interior de 110"},
    {"system": "Premiline 58", "profile": "2173", "description": "Hoja de 75"},
    {"system": "Premiline 58", "profile": "2174", "description": "Hoja de 61"},
    {"system": "Premiline 80", "profile": "6040", "description": "Hoja de 68"},
    {"system": "Premiline 80", "profile": "6041", "description": "Hoja de 84"},
    {"system": "Eurofine 58", "profile": "58201", "description": "Hoja de 77"},
    {"system": "Eurofine 58", "profile": "58203", "description": "Hoja de 107"},
    {"system": "Eurofutur", "profile": "0011", "description": "Hoja de 62"},
    {"system": "Eurofutur", "profile": "0114", "description": "Hoja de 76"},
    {"system": "Eurofutur", "profile": "0116", "description": "Hoja de 98"},
]
PROFILE_LOOKUP = {item["profile"]: item for item in LEAF_PROFILE_CATALOG}


def number_value(text: str) -> float | None:
    cleaned = text.strip()
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_number(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:.1f}".replace(".", ",")


def line_items(page: pdfplumber.page.Page) -> list[dict]:
    words = page.extract_words(
        x_tolerance=1,
        y_tolerance=3,
        keep_blank_chars=False,
        use_text_flow=False,
    )
    grouped: dict[int, list[dict]] = {}
    for word in words:
        key = round(word["top"])
        grouped.setdefault(key, []).append(word)

    lines = []
    for top, items in sorted(grouped.items()):
        items.sort(key=lambda item: item["x0"])
        text = " ".join(item["text"] for item in items)
        lines.append(
            {
                "text": text,
                "page": page.page_number,
                "top": top,
                "x0": min(item["x0"] for item in items),
                "x1": max(item["x1"] for item in items),
            }
        )
    return lines


def plain_text(text: str) -> str:
    return (
        text.replace("ó", "o")
        .replace("Ó", "O")
        .replace("é", "e")
        .replace("É", "E")
        .replace("á", "a")
        .replace("Á", "A")
        .replace("í", "i")
        .replace("Í", "I")
        .replace("ú", "u")
        .replace("Ú", "U")
        .replace("ñ", "n")
        .replace("Ñ", "N")
    )


def split_window_blocks(lines: list[dict]) -> list[dict]:
    starts = [index for index, line in enumerate(lines) if plain_text(line["text"]).startswith("Codigo:")]
    if not starts:
        return [{"lines": lines, "start": 0, "end": len(lines)}]

    blocks = []
    for pos, start in enumerate(starts):
        if pos == 0:
            start = 0
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        blocks.append({"lines": lines[start:end], "start": start, "end": end})
    return blocks


def find_nomenclature(block_lines: list[dict]) -> str:
    for line in block_lines:
        match = re.search(r"Nomenclatura:\s*(.+)$", line["text"], re.I)
        if match:
            return match.group(1).strip()
    for line in block_lines:
        match = re.search(r"Codigo:\s*(.+)$", plain_text(line["text"]), re.I)
        if match:
            return match.group(1).strip()
    return ""


def find_final_measure(block_lines: list[dict]) -> dict:
    width = None
    height = None
    width_line = ""
    height_line = ""

    for line in block_lines:
        text = line["text"]
        match = re.search(r"\bL\s*=\s*([\d.,]+)", text, re.I)
        if match:
            width = number_value(match.group(1))
            width_line = text

        match = re.search(r"\bA\s*=\s*([\d.,]+)", text, re.I)
        if match:
            height = number_value(match.group(1))
            height_line = text

        match = re.search(r"([\d.,]+)\s*=\s*A\b", text, re.I)
        if match:
            height = number_value(match.group(1))
            height_line = text

    if height is None:
        for idx, line in enumerate(block_lines):
            if idx + 2 < len(block_lines):
                if block_lines[idx + 1]["text"].strip() == "=" and block_lines[idx + 2]["text"].strip().upper() == "A":
                    numbers = re.findall(r"[\d]+(?:[,.][\d]+)*", line["text"])
                    if numbers:
                        height = number_value(numbers[-1])
                        height_line = " / ".join(item["text"] for item in block_lines[idx : idx + 3])
                        break

    if height is None:
        for idx, line in enumerate(block_lines):
            nearby = " ".join(item["text"] for item in block_lines[idx : idx + 8])
            if "=" in nearby and re.search(r"\bA\b", nearby):
                numbers = re.findall(r"[\d]+(?:[,.][\d]+)+", line["text"])
                if numbers:
                    height = number_value(numbers[-1])
                    height_line = " / ".join(item["text"] for item in block_lines[idx : idx + 8] if item["text"] in ("=", "A") or numbers[-1] in item["text"])
                    break

    return {
        "width": normalize_number(width),
        "height": normalize_number(height),
        "widthRaw": width_line,
        "heightRaw": height_line,
    }


def find_leaf_profiles(block_lines: list[dict]) -> list[dict]:
    profiles = []
    for line in tronzadoras_lines(block_lines):
        parsed = parse_leaf_line(line)
        if not parsed:
            continue
        profiles.append(parsed)
    return profiles


def find_frame_profiles(block_lines: list[dict]) -> list[dict]:
    profiles = []
    for line in tronzadoras_lines(block_lines):
        parsed = parse_frame_line(line)
        if not parsed:
            continue
        profiles.append(parsed)
    return profiles


def find_inversora_profiles(block_lines: list[dict]) -> list[dict]:
    profiles = []
    for line in block_lines:
        ref_match = re.match(r"^(?P<ref>\d{4,5}[^ ]*)\s+(?P<rest>.+)$", line["text"])
        if not ref_match or "INVERSORA" not in plain_text(ref_match.group("rest")).upper():
            continue
        orient_match = re.search(r"\s(?P<long>[\d,.]+)\s+(?P<pos>[HV])\b", line["text"])
        profiles.append(
            {
                "reference": ref_match.group("ref") if ref_match else "",
                "description": re.sub(r"\s+", " ", ref_match.group("rest")).strip() if ref_match else line["text"],
                "length": normalize_number(number_value(orient_match.group("long"))) if orient_match else "",
                "orientation": orient_match.group("pos").upper() if orient_match else "",
                "page": line["page"],
                "raw": line["text"],
            }
        )
    return profiles


def parse_leaf_line(line: dict) -> dict | None:
    text = line["text"]
    if "HOJA" not in plain_text(text).upper():
        return None

    ref_match = re.match(r"^(?P<ref>\d{4,5}[^ ]*)\s+(?P<rest>.+)$", text)
    if not ref_match:
        return None

    ref = ref_match.group("ref")
    profile = ref.split("---")[0].split(".")[0]
    catalog = PROFILE_LOOKUP.get(profile)
    rest = ref_match.group("rest")
    orient_match = re.search(r"\s(?P<long>[\d,.]+)\s+(?P<pos>[HV])\b", rest)
    series_match = re.search(r"Hoja(?:\s+de)?\s+(?P<series>\d+)", rest, re.I)

    description = rest
    if orient_match:
        description = rest[: orient_match.start()].strip()
        qty_text = rest[: orient_match.start()]
        qtys = re.findall(r"\b\d+\b", qty_text)
    else:
        qtys = []

    quantity = int(qtys[-2]) if len(qtys) >= 2 else 0
    total_quantity = int(qtys[-1]) if len(qtys) >= 1 else 0
    length = number_value(orient_match.group("long")) if orient_match else None

    return {
        "reference": ref,
        "profile": profile,
        "series": series_match.group("series") if series_match else profile_series(catalog),
        "description": re.sub(r"\s+\d+\s+\d+$", "", re.sub(r"\s+", " ", description).strip()),
        "catalogSystem": catalog["system"] if catalog else "",
        "catalogDescription": catalog["description"] if catalog else "",
        "quantity": quantity,
        "totalQuantity": total_quantity,
        "length": normalize_number(length),
        "orientation": orient_match.group("pos").upper() if orient_match else "",
        "page": line["page"],
        "raw": text,
    }


def parse_frame_line(line: dict) -> dict | None:
    text = line["text"]
    plain = plain_text(text).upper()
    if "MARCO" not in plain or "HOJA" in plain:
        return None

    ref_match = re.match(r"^(?P<ref>\d{4,5}[^ ]*)\s+(?P<rest>.+)$", text)
    if not ref_match:
        return None

    ref = ref_match.group("ref")
    rest = ref_match.group("rest")
    orient_match = re.search(r"\s(?P<long>[\d,.]+)\s+(?P<pos>[HV])\b", rest)
    series_match = re.search(r"Marco(?:\s+de)?\s+(?P<series>\d+)", rest, re.I)
    qtys = []
    description = rest
    if orient_match:
        description = rest[: orient_match.start()].strip()
        qtys = re.findall(r"\b\d+\b", description)

    length = number_value(orient_match.group("long")) if orient_match else None
    return {
        "reference": ref,
        "profile": ref.split("---")[0].split(".")[0],
        "series": series_match.group("series") if series_match else "",
        "description": re.sub(r"\s+\d+\s+\d+$", "", re.sub(r"\s+", " ", description).strip()),
        "quantity": int(qtys[-2]) if len(qtys) >= 2 else 0,
        "totalQuantity": int(qtys[-1]) if len(qtys) >= 1 else 0,
        "length": normalize_number(length),
        "orientation": orient_match.group("pos").upper() if orient_match else "",
        "page": line["page"],
        "raw": text,
    }


def profile_series(catalog: dict | None) -> str:
    if not catalog:
        return ""
    match = re.search(r"\b(?:de|hoja)\s+(\d+)\b", catalog["description"], re.I)
    return match.group(1) if match else ""


def tronzadoras_lines(block_lines: list[dict]) -> list[dict]:
    start = None
    for idx, line in enumerate(block_lines):
        text = plain_text(line["text"]).upper()
        if "TRONZADORAS" in text and "PERFIL" in text:
            start = idx + 1
            break

    if start is None:
        return []

    end = len(block_lines)
    section_re = re.compile(r"^\s*\d{2}\s+[A-Z ]+")
    for idx in range(start, len(block_lines)):
        text = plain_text(block_lines[idx]["text"]).upper()
        if section_re.match(text):
            end = idx
            break

    return block_lines[start:end]


def find_mosquito_notes(block_lines: list[dict]) -> list[dict]:
    notes = []
    for line in block_lines:
        if "MOSQUIT" in line["text"].upper():
            notes.append({"page": line["page"], "text": line["text"], "top": line["top"]})
    return notes


def extract_document_info(lines: list[dict]) -> dict:
    budget = ""
    client = ""
    for line in lines:
        text = re.sub(r"\s+", " ", line["text"]).strip()
        plain = plain_text(text)
        if not budget:
            match = re.search(r"Presupuesto\s*n[º°o]?\s*[:#-]?\s*([A-Z0-9,./-]+)", plain, re.I)
            if match:
                budget = match.group(1).strip(" .,-")
        if not client:
            match = re.search(r"Cliente\s*:\s*(.+)$", text, re.I)
            if match:
                value = match.group(1).strip()
                value = re.split(r"\s+(?:Codigo|Nomenclatura|Hoja\s+de\s+Trabajo|Presupuesto)\s*:?", value, 1, flags=re.I)[0]
                client = value.strip(" .,-")
        if budget and client:
            break
    return {"budget": budget, "client": client}


def extract_pdf(path: Path, display_name: str | None = None) -> dict:
    all_lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            all_lines.extend(line_items(page))

    document_info = extract_document_info(all_lines)
    blocks = split_window_blocks(all_lines)
    windows = []
    for index, block in enumerate(blocks, start=1):
        block_lines = block["lines"]
        text = "\n".join(line["text"] for line in block_lines)
        notes = find_mosquito_notes(block_lines)
        profiles = find_leaf_profiles(block_lines)
        frame_profiles = find_frame_profiles(block_lines)
        inversora_profiles = find_inversora_profiles(block_lines)
        measure = find_final_measure(block_lines)
        nomenclature = find_nomenclature(block_lines)
        pages = sorted({line["page"] for line in block_lines})
        has_mosquito = bool(notes)

        if has_mosquito or profiles or nomenclature:
            windows.append(
                {
                    "index": index,
                    "nomenclature": nomenclature,
                    "pages": pages,
                    "hasMosquito": has_mosquito,
                    "mosquitoNotes": notes,
                    "finalMeasure": measure,
                    "leafProfiles": profiles,
                    "frameProfiles": frame_profiles,
                    "inversoraProfiles": inversora_profiles,
                    "hasInversora": bool(inversora_profiles),
                    "rawPreview": text[:1800],
                    "confidence": confidence(has_mosquito, measure, profiles),
                }
            )

    mosquito_windows = [item for item in windows if item["hasMosquito"]]
    return {
        "fileName": display_name or path.name,
        "windowCount": len(windows),
        "mosquitoCount": len(mosquito_windows),
        "documentInfo": document_info,
        "windows": windows,
        "mosquitoWindows": mosquito_windows,
    }


def confidence(has_mosquito: bool, measure: dict, profiles: list[dict]) -> str:
    if has_mosquito and profiles:
        return "alta"
    if has_mosquito:
        return "media"
    return "revisar"


def parse_pdf_uploads(headers, rfile) -> list[tuple[str, bytes]] | None:
    content_type = headers.get("Content-Type", "")
    boundary_match = re.search(r'boundary="?([^";]+)"?', content_type)
    if "multipart/form-data" not in content_type or not boundary_match:
        return None

    try:
        content_length = int(headers.get("Content-Length", "0"))
    except ValueError:
        return None

    body = rfile.read(content_length)
    boundary = ("--" + boundary_match.group(1)).encode("utf-8")

    uploads = []
    for part in body.split(boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].rstrip(b"\r\n")

        if b"\r\n\r\n" in part:
            raw_headers, data = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            raw_headers, data = part.split(b"\n\n", 1)
        else:
            continue

        header_text = raw_headers.decode("latin-1", errors="ignore")
        if 'name="pdf"' not in header_text:
            continue

        filename_match = re.search(r'filename="([^"]*)"', header_text)
        filename = filename_match.group(1) if filename_match else "htf.pdf"
        if data.endswith(b"\r\n"):
            data = data[:-2]
        if data:
            uploads.append((filename or "htf.pdf", data))

    return uploads or None


def merge_pdf_results(results: list[dict], errors: list[dict] | None = None) -> dict:
    if not results:
        return {
            "fileName": "-",
            "fileNames": [],
            "windowCount": 0,
            "mosquitoCount": 0,
            "documentInfo": {"budget": "", "client": ""},
            "windows": [],
            "mosquitoWindows": [],
            "errors": errors or [],
        }

    windows = []
    mosquito_windows = []
    file_names = []
    budgets = []
    clients_by_key = {}
    for result in results:
        file_name = result.get("fileName", "")
        if file_name:
            file_names.append(file_name)
        budget = result.get("documentInfo", {}).get("budget", "").strip()
        client = result.get("documentInfo", {}).get("client", "").strip()
        if budget:
            budgets.append(budget)
        if client:
            client_key = re.sub(r"\s+", " ", client).strip().casefold()
            clients_by_key.setdefault(client_key, client)
        for collection_name, target in (("windows", windows), ("mosquitoWindows", mosquito_windows)):
            for item in result.get(collection_name, []):
                clone = dict(item)
                clone["sourceFile"] = file_name
                clone["index"] = len(target) + 1
                target.append(clone)

    file_label = file_names[0] if len(file_names) == 1 else f"{len(file_names)} PDFs"
    client_values = list(clients_by_key.values())
    warnings = []
    if len(results) > 1 and len(client_values) > 1:
        warnings.append({
            "type": "client-mismatch",
            "message": "Los PDFs cargados tienen clientes diferentes. Revisa antes de fabricar.",
            "clients": client_values,
        })
    document_info = {
        "budget": budgets[0] if len(results) == 1 and budgets else "",
        "client": client_values[0] if len(client_values) == 1 else ("REVISAR CLIENTES" if client_values else ""),
    }
    return {
        "fileName": file_label,
        "fileNames": file_names,
        "windowCount": len(windows),
        "mosquitoCount": len(mosquito_windows),
        "documentInfo": document_info,
        "windows": windows,
        "mosquitoWindows": mosquito_windows,
        "errors": errors or [],
        "warnings": warnings,
    }


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if not self.require_auth():
            return
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json({"ok": True})
            return
        if path in ("/", "/index.html"):
            self.send_file(ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/assets/"):
            target = (ROOT / path.lstrip("/")).resolve()
            assets_root = (ROOT / "assets").resolve()
            if target.exists() and target.is_file() and assets_root in target.parents:
                self.send_file(target, content_type_for(target))
                return
            self.send_json({"error": "Archivo no encontrado."}, status=404)
            return
        if path == "/api/sample":
            if not SAMPLE_PDF.exists():
                self.send_json({"error": "No encontré el PDF de ejemplo."}, status=404)
                return
            self.send_json(extract_pdf(SAMPLE_PDF))
            return
        if path == "/api/profiles":
            self.send_json({"profiles": LEAF_PROFILE_CATALOG})
            return
        self.send_json({"error": "Ruta no encontrada."}, status=404)

    def do_POST(self) -> None:
        if not self.require_auth():
            return
        path = urlparse(self.path).path
        if path != "/api/extract":
            self.send_json({"error": "Ruta no encontrada."}, status=404)
            return

        uploads = parse_pdf_uploads(self.headers, self.rfile)
        if uploads is None:
            self.send_json({"error": "Sube uno o mas PDFs en el campo pdf."}, status=400)
            return

        results = []
        errors = []
        for filename, file_data in uploads:
            suffix = Path(filename or "htf.pdf").suffix or ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_data)
                tmp_path = Path(tmp.name)
            try:
                results.append(extract_pdf(tmp_path, filename or tmp_path.name))
            except Exception as exc:
                errors.append({"fileName": filename or "htf.pdf", "error": str(exc)})
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        if not results and errors:
            self.send_json({"error": "No se pudo leer ningun PDF.", "errors": errors}, status=500)
            return
        self.send_json(merge_pdf_results(results, errors))

    def send_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")

    def require_auth(self) -> bool:
        password = os.environ.get("APP_PASSWORD", "").strip()
        if not password:
            return True

        username = os.environ.get("APP_USER", "brezza")
        auth = self.headers.get("Authorization", "")
        prefix = "Basic "
        if auth.startswith(prefix):
            try:
                decoded = base64.b64decode(auth[len(prefix) :]).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                if user == username and pwd == password:
                    return True
            except Exception:
                pass

        self.send_response(401)
        self.send_cors_headers()
        self.send_header("WWW-Authenticate", 'Basic realm="Mosquiteros Brezza"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Autenticacion requerida.")
        return False


def main() -> None:
    port = int(os.environ.get("PORT", "8810"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"HTF Brezza listo en http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
