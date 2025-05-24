import flask
from flask import request, jsonify
import requests
from bs4 import BeautifulSoup
import time
import logging

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
    
    headers = {
        'User-Agent': COMMON_USER_AGENT
    }

    try:
        logging.info(f"Fetching archive page: {PASTEBIN_ARCHIVE_URL}")
        archive_response = requests.get(PASTEBIN_ARCHIVE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
        archive_response.raise_for_status()
        
        soup = BeautifulSoup(archive_response.content, 'html.parser')
        paste_link_elements = soup.select('table.maintable tr td:first-child a')
        
        if not paste_link_elements:
            logging.warning("Could not find paste links on archive page. Structure might have changed.")
            return jsonify({"error": "Could not parse Pastebin archive page. The page structure may have changed or no pastes found."}), 500

        logging.info(f"Found {len(paste_link_elements)} potential pastes in archive. Checking up to {MAX_PASTES_TO_CHECK}.")
        
        pastes_processed_count = 0
        for link_element in paste_link_elements:
            if pastes_processed_count >= MAX_PASTES_TO_CHECK:
                logging.info(f"Reached MAX_PASTES_TO_CHECK limit ({MAX_PASTES_TO_CHECK}).")
                break

            paste_relative_url = link_element.get('href')
            if not paste_relative_url or not paste_relative_url.startswith('/') or '/archive/' in paste_relative_url:
                continue

            paste_id = paste_relative_url[1:] 
            
            if '/' in paste_id:
                continue

            full_paste_url = f"{PASTEBIN_BASE_URL}/{paste_id}"
            raw_content_url = f"{PASTEBIN_RAW_URL_BASE}{paste_id}"

            logging.info(f"Processing paste ID: {paste_id} (URL: {raw_content_url})")

            try:
                time.sleep(DELAY_BETWEEN_PASTE_REQUESTS)
                paste_content_response = requests.get(raw_content_url, headers=headers, timeout=REQUEST_TIMEOUT)
                
                if paste_content_response.status_code == 404:
                    logging.warning(f"Paste {paste_id} not found (404). Skipping.")
                    continue
                paste_content_response.raise_for_status()
                
                paste_text_content = paste_content_response.text

                if query_phrase.lower() in paste_text_content.lower():
                    logging.info(f"Query '{query_phrase}' found in paste {paste_id}.")
                    
                    snippet = generate_snippet(paste_text_content, query_phrase)
                    if snippet:
                        results.append({
                            "link": full_paste_url, 
                            "snippet": snippet
                        })
                else:
                    logging.debug(f"Query '{query_phrase}' not found in paste {paste_id}.")
                
                pastes_processed_count += 1

            except requests.exceptions.Timeout:
                logging.warning(f"Timeout while fetching paste {paste_id} from {raw_content_url}. Skipping.")
            except requests.exceptions.RequestException as e_paste:
                logging.error(f"Error fetching or processing paste {paste_id} from {raw_content_url}: {e_paste}")
            except Exception as e_general_paste:
                logging.error(f"Unexpected error processing paste {paste_id}: {e_general_paste}")
            
        logging.info(f"Search for '{query_phrase}' completed. Found {len(results)} results after checking {pastes_processed_count} pastes.")

    except requests.exceptions.Timeout:
        logging.error(f"Timeout while fetching Pastebin archive page: {PASTEBIN_ARCHIVE_URL}")
        return jsonify({"error": "Could not connect to Pastebin archive (timeout). Please try again later."}), 504
    except requests.exceptions.RequestException as e_archive:
        logging.error(f"Error connecting to Pastebin archive: {e_archive}")
        return jsonify({"error": f"Could not connect to Pastebin archive: {e_archive}"}), 503 
    except Exception as e_global:
        logging.critical(f"An unexpected server error occurred: {e_global}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred. Please check server logs."}), 500

    return jsonify(results)

@app.route('/links', methods=['GET'])
def get_pastebin_links():
    headers = {
        'User-Agent': COMMON_USER_AGENT
    }

    try:
        logging.info(f"Fetching archive page: {PASTEBIN_ARCHIVE_URL}")
        archive_response = requests.get(PASTEBIN_ARCHIVE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
        archive_response.raise_for_status()
        
        soup = BeautifulSoup(archive_response.content, 'html.parser')
        paste_link_elements = soup.select('table.maintable tr td:first-child a')
        
        if not paste_link_elements:
            logging.warning("Could not find paste links on archive page. Structure might have changed.")
            return jsonify({"error": "Could not parse Pastebin archive page. The page structure may have changed or no pastes found."}), 500

        paste_links = []
        for link_element in paste_link_elements:
            paste_relative_url = link_element.get('href')
           
            if not paste_relative_url or not paste_relative_url.startswith('/') or '/archive/' in paste_relative_url:
                continue

            paste_id = paste_relative_url[1:] 
            
            if '/' in paste_id:
                continue

            full_paste_url = f"{PASTEBIN_BASE_URL}/{paste_id}"
            raw_content_url = f"{PASTEBIN_RAW_URL_BASE}{paste_id}"
            
            paste_links.append({
                "id": paste_id,
                "view_url": full_paste_url,
                "raw_url": raw_content_url
            })

        logging.info(f"Found {len(paste_links)} paste links in archive.")
        return jsonify({
            "total_links": len(paste_links),
            "links": paste_links
        })

    except requests.exceptions.Timeout:
        logging.error(f"Timeout while fetching Pastebin archive page: {PASTEBIN_ARCHIVE_URL}")
        return jsonify({"error": "Could not connect to Pastebin archive (timeout). Please try again later."}), 504
    except requests.exceptions.RequestException as e_archive:
        logging.error(f"Error connecting to Pastebin archive: {e_archive}")
        return jsonify({"error": f"Could not connect to Pastebin archive: {e_archive}"}), 503
    except Exception as e_global:
        logging.critical(f"An unexpected server error occurred: {e_global}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred. Please check server logs."}), 500

if __name__ == '__main__':
    print("Starting Flask development server on http://127.0.0.1:5001/")
    print("To test, open your browser or use curl, e.g.:")
    print("http://127.0.0.1:5001/search?q=python+example")
    print("http://127.0.0.1:5001/search?q=api+key")
    app.run(host='0.0.0.0', port=5001, debug=True)