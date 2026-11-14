import os, csv, json, time
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("SemanticScholar_API_KEY")
if not API_KEY:
    raise ValueError("Missing SemanticScholar_API_KEY")

BASE = "https://api.semanticscholar.org/graph/v1"
YEAR, FOS, LIMIT, BATCH = "2026", "Computer Science,Engineering", 1000, 100
SAMPLE_FILE = "semantic_scholar_sample.csv"
OUT_FILE = "semantic_scholar_2026.csv"
STATE_FILE = "crawler_state.json"

FIELDS = (
    "title,abstract,venue,year,referenceCount,citationCount,"
    "influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,"
    "s2FieldsOfStudy,publicationTypes,publicationDate,journal,authors,"
    "externalIds,url,tldr"
)
COLS = ["paperId"] + FIELDS.split(",")

session = requests.Session()
session.headers.update({"x-api-key": API_KEY})
last_req = 0.0


def api_req(method, url, **kwargs):
    global last_req

    for attempt in range(6):
        wait = 1.1 - (time.monotonic() - last_req)
        if wait > 0:
            time.sleep(wait)

        last_req = time.monotonic()
        print(f"[API] {method} {url.split('/')[-1]} | Try {attempt + 1}/6",
              flush=True)

        try:
            res = session.request(method, url, timeout=90, **kwargs)
            print(f"[API] HTTP {res.status_code}", flush=True)

            if res.status_code == 429 or res.status_code >= 500:
                retry = res.headers.get("Retry-After", "")
                delay = float(retry) if retry.isdigit() else min(2 ** attempt, 30)
                print(f"[RETRY] Waiting {delay}s | {res.text[:300]}", flush=True)
                time.sleep(delay)
                continue

            res.raise_for_status()
            return res.json()

        except requests.HTTPError:
            raise
        except requests.RequestException as e:
            if attempt == 5:
                raise
            delay = min(2 ** attempt, 30)
            print(f"[NETWORK ERROR] {e} | Retry in {delay}s", flush=True)
            time.sleep(delay)

    raise RuntimeError(f"API failed after retries: {url}")


def encode_row(row):
    return {
        k: json.dumps(v, ensure_ascii=False)
        if isinstance(v, (dict, list)) else v
        for k, v in row.items()
    }


def save_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(encode_row(row) for row in rows)


def load_seen():
    if not os.path.exists(OUT_FILE):
        return set()
    with open(OUT_FILE, newline="", encoding="utf-8-sig") as f:
        return {row["paperId"] for row in csv.DictReader(f) if row.get("paperId")}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"token": None, "page_no": 0, "done": False}

    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)

    if state.get("year") != YEAR or state.get("fos") != FOS:
        raise ValueError("Crawler state belongs to different YEAR/FOS settings.")

    return state


def save_state(token, page_no, done=False):
    state = {
        "year": YEAR, "fos": FOS,
        "token": token, "page_no": page_no, "done": done
    }
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def get_papers(ids):
    return api_req(
        "POST", f"{BASE}/paper/batch",
        params={"fields": FIELDS}, json={"ids": ids}
    )


def main():
    url = f"{BASE}/paper/search/bulk"
    seen = load_seen()
    state = load_state()

    print("=" * 55)
    print(f"Year: {YEAR} | Fields: {FOS} | Batch: {BATCH}")
    print(f"Existing papers: {len(seen):,}")
    print("=" * 55)

    if state["done"]:
        print("[DONE] Previous crawl is already complete.")
        return

    params = {
        "year": YEAR, "fieldsOfStudy": FOS,
        "fields": "title", "limit": LIMIT
    }

    # First run: fetch the first page and ask for sample confirmation.
    if state["page_no"] == 0 and state["token"] is None:
        print("[SEARCH] Fetching first page...")
        page = api_req("GET", url, params=params)
        ids = [p["paperId"] for p in page.get("data", [])]

        if not ids:
            print("[STOP] No papers found.")
            save_state(None, 0, done=True)
            return

        first_batch = get_papers(ids[:BATCH])
        save_csv(SAMPLE_FILE, first_batch[:5])
        print(f"[SAMPLE] Saved {min(5, len(first_batch))} papers -> {SAMPLE_FILE}")

        if input("Continue full crawl? (y/n): ").strip().lower() != "y":
            print("[STOP] Sample retained. Run again to start the full crawl.")
            return

        # Keep the first search page and first detail batch for reuse.
        page_no = 1
        first_page = page
        first_ids = ids
    else:
        first_page = None
        first_ids = None
        first_batch = None
        page_no = state["page_no"] + 1

    # Append to existing CSV; create header only for a new/empty file.
    new_file = not os.path.exists(OUT_FILE) or os.path.getsize(OUT_FILE) == 0
    with open(OUT_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        if new_file:
            writer.writeheader()

        def write_rows(rows):
            added = 0
            for row in rows:
                pid = row.get("paperId")
                if pid and pid not in seen:
                    writer.writerow(encode_row(row))
                    seen.add(pid)
                    added += 1
            f.flush()
            print(f"[SAVE] +{added} new | Total unique: {len(seen):,}",
                  flush=True)

        # Process first page using already-fetched details.
        if first_page is not None:
            print(f"[PAGE {page_no}] {len(first_ids)} papers")
            write_rows(first_batch)

            for i in range(BATCH, len(first_ids), BATCH):
                batch_ids = first_ids[i:i + BATCH]
                print(f"[DETAIL] Batch {i // BATCH + 1} | {len(batch_ids)} IDs")
                write_rows(get_papers(batch_ids))

            next_token = first_page.get("token")
            save_state(next_token, page_no, done=not bool(next_token))

        else:
            next_token = state["token"]

        # Continue from the saved token. If interrupted during a page,
        # the token remains unchanged and that page is safely retried.
        while next_token:
            page_no += 1
            print(f"\n[SEARCH] Fetching page {page_no}...")
            page = api_req("GET", url, params={
                **params, "token": next_token
            })
            ids = [p["paperId"] for p in page.get("data", [])]
            print(f"[PAGE {page_no}] Found {len(ids)} papers")

            for i in range(0, len(ids), BATCH):
                batch_ids = ids[i:i + BATCH]
                print(f"[DETAIL] Batch {i // BATCH + 1} | {len(batch_ids)} IDs")
                write_rows(get_papers(batch_ids))

            next_token = page.get("token")
            save_state(next_token, page_no, done=not bool(next_token))

    print(f"\n[COMPLETED] {len(seen):,} unique papers -> {OUT_FILE}")


if __name__ == "__main__":
    main()
