import flask
from flask import request, jsonify
import requests
from bs4 import BeautifulSoup
import time
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = flask.Flask(__name__)

PASTEBIN_ARCHIVE_URL = "https://pastebin.com/archive"
PASTEBIN_BASE_URL = "https://pastebin.com"
PASTEBIN_RAW_URL_BASE = "https://pastebin.com/raw/"
MAX_PASTES_TO_CHECK = 100
SNIPPET_CONTEXT_LENGTH = 80
COMMON_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
REQUEST_TIMEOUT = 10
DELAY_BETWEEN_PASTE_REQUESTS = 0.2

def generate_snippet(text_content, query_phrase):
    try:
        query_lower = query_phrase.lower()
        text_lower = text_content.lower()
        idx = text_lower.find(query_lower)
        if idx == -1:
            return None
        start_index = max(0, idx - SNIPPET_CONTEXT_LENGTH)
        end_index = min(len(text_content), idx + len(query_phrase) + SNIPPET_CONTEXT_LENGTH)
        prefix = "..." if start_index > 0 else ""
        suffix = "..." if end_index < len(text_content) else ""
        snippet = text_content[start_index:end_index]
        return f"{prefix}{snippet}{suffix}".strip()
    except Exception as e:
        logging.error(f"Error generating snippet: {e}")
        return text_content[:SNIPPET_CONTEXT_LENGTH*2] + "..." if len(text_content) > SNIPPET_CONTEXT_LENGTH*2 else text_content

@app.route('/search', methods=['GET'])
def search_pastebin_pastes():
    query_phrase = request.args.get('q')
    if not query_phrase:
        logging.warning("Search attempt with no query parameter.")
        return jsonify({"error": "Query parameter 'q' is required. Use /search?q=your_query"}), 400
    if len(query_phrase) < 3:
        logging.warning(f"Search attempt with too short query: '{query_phrase}'")
        return jsonify({"error": "Query phrase must be at least 3 characters long."}), 400
    logging.info(f"Received search request for query: '{query_phrase}'")
    results = []
    headers = { 'User-Agent': COMMON_USER_AGENT }
    try:
        archive_response = requests.get(PASTEBIN_ARCHIVE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
        archive_response.raise_for_status()
        soup = BeautifulSoup(archive_response.content, 'html.parser')
        paste_link_elements = soup.select('table.maintable tr td:first-child a')
        if not paste_link_elements:
            logging.warning("Could not find paste links on archive page. Structure might have changed.")
            return jsonify({"error": "Could not parse Pastebin archive page. The page structure may have changed or no pastes found."}), 500
        pastes_processed_count = 0
        for link_element in paste_link_elements:
            if pastes_processed_count >= MAX_PASTES_TO_CHECK:
                break
            paste_relative_url = link_element.get('href')
            if not paste_relative_url or not paste_relative_url.startswith('/') or '/archive/' in paste_relative_url:
                continue
            paste_id = paste_relative_url[1:]
            if '/' in paste_id:
                continue
            full_paste_url = f"{PASTEBIN_BASE_URL}/{paste_id}"
            raw_content_url = f"{PASTEBIN_RAW_URL_BASE}{paste_id}"
            try:
                time.sleep(DELAY_BETWEEN_PASTE_REQUESTS)
                paste_content_response = requests.get(raw_content_url, headers=headers, timeout=REQUEST_TIMEOUT)
                if paste_content_response.status_code == 404:
                    continue
                paste_content_response.raise_for_status()
                paste_text_content = paste_content_response.text
                if query_phrase.lower() in paste_text_content.lower():
                    snippet = generate_snippet(paste_text_content, query_phrase)
                    if snippet:
                        results.append({"link": full_paste_url, "snippet": snippet})
                pastes_processed_count += 1
            except Exception:
                continue
    except Exception:
        return jsonify({"error": "Unexpected error during search."}), 500
    return jsonify(results)

@app.route('/links', methods=['GET'])
def get_pastebin_links():
    headers = { 'User-Agent': COMMON_USER_AGENT }
    try:
        archive_response = requests.get(PASTEBIN_ARCHIVE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
        archive_response.raise_for_status()
        soup = BeautifulSoup(archive_response.content, 'html.parser')
        paste_link_elements = soup.select('table.maintable tr td:first-child a')
        if not paste_link_elements:
            return jsonify({"error": "No paste links found."}), 500
        paste_links = []
        for link_element in paste_link_elements:
            paste_relative_url = link_element.get('href')
            if not paste_relative_url or not paste_relative_url.startswith('/') or '/archive/' in paste_relative_url:
                continue
            paste_id = paste_relative_url[1:]
            if '/' in paste_id:
                continue
            paste_links.append({
                "id": paste_id,
                "view_url": f"{PASTEBIN_BASE_URL}/{paste_id}",
                "raw_url": f"{PASTEBIN_RAW_URL_BASE}{paste_id}"
            })
        return jsonify({"total_links": len(paste_links), "links": paste_links})
    except Exception:
        return jsonify({"error": "Unexpected error."}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
