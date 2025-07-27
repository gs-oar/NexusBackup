import requests
import os
import json
import time
import math
import shutil
from github import Github
import re
from packaging.version import parse as parse_version
from concurrent.futures import ThreadPoolExecutor

# --- Step 1: Helper Functions ---
def create_release_tag(uid, mod_name, version):
    """Creates a human-readable but unique tag for a release."""
    slug_part = '-'.join(mod_name.lower().split()[:3])
    safe_slug = re.sub(r'[^a-z0-9-]', '', slug_part)
    return f"{safe_slug}-{uid}-v{version}"

def format_nexus_description(text):
    """
    Converts a Nexus description (mix of BBCode, HTML breaks, and text)
    into clean, GitHub-flavored Markdown.
    """
    if not text: return "No description provided."

    # --- Pre-processing ---
    # Convert HTML line breaks to newlines and normalize line endings
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = text.replace('\r\n', '\n')

    # --- Block-level BBCode to Markdown/HTML ---
    # [hr] to Markdown horizontal rule
    text = re.sub(r'\[hr\]', '\n---\n', text, flags=re.IGNORECASE)

    # [spoiler=Title]...[/spoiler] and [spoiler]...[/spoiler] to <details> tag
    text = re.sub(r'\[spoiler=(.*?)\](.*?)\[/spoiler\]', r'<details><summary>\1</summary>\n\n\2\n\n</details>', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[spoiler\](.*?)\[/spoiler\]', r'<details><summary>Spoiler</summary>\n\n\1\n\n</details>', text, flags=re.IGNORECASE | re.DOTALL)

    # [quote=Author]...[/quote] and [quote]...[/quote] to Markdown blockquotes
    text = re.sub(r'\[quote=(.*?)\](.*?)\s*\[/quote\]', r'> **\1 wrote:**\n> \2', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[quote\](.*?)\s*\[/quote\]', r'> \1', text, flags=re.IGNORECASE | re.DOTALL)
    # This part handles multi-line quotes by adding '>' to each line within the block.
    text = '\n'.join([f'> {line}' if line.startswith(' ') and i > 0 and text.splitlines()[i-1].startswith('>') else line for i, line in enumerate(text.splitlines())])

    # [list] and [*] for bullet points
    text = re.sub(r'\[\*\](.*?)(?=\[\*\]|\[/list\])', r'\n* \1', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[/?list\]', '', text, flags=re.IGNORECASE)

    # --- Inline BBCode to Markdown ---
    # Bold, Italic, Strikethrough
    text = re.sub(r'\[b\](.*?)\[/b\]', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[i\](.*?)\[/i\]', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\[s\](.*?)\[/s\]', r'~~\1~~', text, flags=re.IGNORECASE | re.DOTALL)

    # Images and URLs
    text = re.sub(r'\[img\](.*?)\[/img\]', r'![Image](\1)', text, flags=re.IGNORECASE)
    text = re.sub(r'\[url=(.*?)\](.*?)\[/url\]', r'[\2](\1)', text, flags=re.IGNORECASE)
    text = re.sub(r'\[url\](.*?)\[/url\]', r'<\1>', text, flags=re.IGNORECASE)

    # --- Strip unsupported tags ---
    # This will remove tags like [size=...], [color=...], [font=...], [u]...[/u] etc.
    # It keeps the content inside the tags.
    text = re.sub(r'\[/?(size|color|font|u|center|right|left|indent)(=[^\]]*)?\]', '', text, flags=re.IGNORECASE)

    # --- Post-processing ---
    # Collapse excess newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
    
def download_file(job):
    """
    Downloads a single file based on a job dictionary.
    This function is designed to be run in a separate thread.
    """
    url = job['url']
    destination_path = job['path']
    try:
        print(f"    [Thread] Downloading '{os.path.basename(destination_path)}'...")
        with requests.get(url, stream=True, timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT)) as r:
            r.raise_for_status()
            with open(destination_path, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        job['downloaded_path'] = destination_path
        return job
    except Exception as e:
        print(f"    [Thread] ERROR downloading {os.path.basename(destination_path)}: {e}")
        job['downloaded_path'] = None
        return job

def requests_with_retry(method, url, **kwargs):
    """
    Makes an HTTP request with a retry mechanism for transient errors.
    """
    retries = 0
    while retries < MAX_RETRIES:
        try:
            # Add a default timeout if not specified in the call
            if 'timeout' not in kwargs:
                kwargs['timeout'] = REQUESTS_TIMEOUT
            
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return response
        
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            retries += 1
            if retries >= MAX_RETRIES:
                print(f"  > ERROR: Max retries reached for {method} {url}. Last error: {e}")
                raise  # Re-raise the last exception after all retries fail
            
            wait_time = BACKOFF_FACTOR * (2 ** (retries - 1))
            print(f"  > WARNING: Request failed ({e}). Retrying in {wait_time} seconds... ({retries}/{MAX_RETRIES})")
            time.sleep(wait_time)
            
    # This line should not be reached if MAX_RETRIES > 0, but as a fallback:
    raise Exception(f"Request failed after {MAX_RETRIES} retries for {url}")
    
def sanitize_filename(filename, mod_id, version):
    """
    Cleans Nexus-style metadata from a filename and appends a canonical version.
    Example: "MyMod-12345-1-0.7z" -> "MyMod-v1.0.7z"
    """
    name_part, extension = os.path.splitext(filename)
    # This pattern looks for the mod ID, optionally followed by any number of
    # hyphen-separated numbers (like version parts or timestamps) at the end of the name.
    pattern = rf'-{mod_id}(?:-\d+)*$'
    clean_name_part = re.sub(pattern, '', name_part).strip()
    # If the name becomes empty after cleaning (e.g., filename was just "12345-1.zip"),
    # we fall back to a safe default name.
    if not clean_name_part:
        clean_name_part = f"modfile-{mod_id}"
    return f"{clean_name_part}-v{version}{extension}"
    
# --- Step 2: Configuration ---
print("--- Step 1: CONFIGURATION ---")
V1_API_KEY = os.environ.get("NEXUSMODS_V1_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPOSITORY")
USER_ID_TO_TRACK = os.environ.get("NEXUS_USERID")
DOWNLOADS_DIR = "downloads"
THROTTLE_LIMIT = 30
DATA_FILE = "data.json"
INVALID_FILE_CATEGORIES = {"ARCHIVED", "ARCHIVE"}
MAX_WORKERS = 4

REQUESTS_TIMEOUT = 30  # Timeout for API calls in seconds
DOWNLOAD_CONNECT_TIMEOUT = 15 # Time to establish a download connection
DOWNLOAD_READ_TIMEOUT = 120 # Time to wait for data once connected
MAX_RETRIES = 3
BACKOFF_FACTOR = 2  # Seconds to wait after first failure

# --- Safety Checks ---
if not V1_API_KEY:
    print("FATAL ERROR: NEXUSMODS_V1_API_KEY secret is not set.")
    exit(1)
if not GITHUB_TOKEN:
    print("FATAL ERROR: GITHUB_TOKEN is not available.")
    exit(1)
if not USER_ID_TO_TRACK:
    print("FATAL ERROR: NEXUS_USERID secret is not set.")
    exit(1)

# --- Step 3: Connect to GitHub ---
print("\n--- Step 2: CONNECTING TO GITHUB REPO ---")
g = Github(GITHUB_TOKEN)
repo = g.get_repo(GITHUB_REPO_NAME)
print(f"Successfully connected to repo: {repo.full_name}")
releases = repo.get_releases()
EXISTING_RELEASES = {r.tag_name for r in releases}
print(f"Found {len(EXISTING_RELEASES)} existing releases.")

# --- Step 4: Load Existing Mod Data ---
print(f"\n--- Step 3: LOADING LOCAL DATA ---")
indexed_known_mods = {}
try:
    with open(DATA_FILE, 'r') as f:
        indexed_known_mods = json.load(f)
    print(f"Loaded {len(indexed_known_mods)} mod entries from {DATA_FILE}.")
except (FileNotFoundError, json.JSONDecodeError):
    print(f"{DATA_FILE} not found or invalid. Starting with an empty dataset.")

# --- Step 5: Fetch Full Mod List from Nexus Mods API ---
print("\n--- Step 4: GETTING MOD LIST FROM V2 API ---")
V2_GQL_URL = "https://api.nexusmods.com/v2/graphql"
graphql_query = """
    query GetUserMods($uploaderId: String!, $count: Int, $offset: Int) {
      mods(filter: {uploaderId: {value: $uploaderId, op: EQUALS}}, count: $count, offset: $offset) {
        totalCount
        nodes { uid, modId, name, version, summary, description, pictureUrl, game { domainName } }
      }
    }
"""
all_mods_from_api = []
try:
    print("Fetching total mod count...")
    initial_response = requests_with_retry(
        "POST", V2_GQL_URL, 
        json={"query": graphql_query, "variables": {"uploaderId": USER_ID_TO_TRACK, "count": 1, "offset": 0}}
    )
    response_json = initial_response.json()
    if "errors" in response_json:
        print("FATAL ERROR: GraphQL API returned errors.")
        print(json.dumps(response_json["errors"], indent=2))
        exit(1)
        
    total_count = response_json["data"]["mods"]["totalCount"]
    print(f"Total mods to fetch from API: {total_count}")
    page_size = 50
    num_pages = math.ceil(total_count / page_size)
    
    for page_num in range(num_pages):
        offset = page_num * page_size
        print(f"Fetching page {page_num + 1}/{num_pages}...")
        variables = {"uploaderId": USER_ID_TO_TRACK, "count": page_size, "offset": offset}
        
        response = requests_with_retry("POST", V2_GQL_URL, json={"query": graphql_query, "variables": variables})
        page_json = response.json()
        
        if "errors" in page_json:
            print(f"ERROR: GraphQL API returned errors on page {page_num + 1}.")
            print(json.dumps(page_json["errors"], indent=2))
            continue
        all_mods_from_api.extend(page_json["data"]["mods"]["nodes"])

except Exception as e:
    print(f"FATAL ERROR: An unexpected error occurred while fetching the mod list. Error: {e}")
    exit(1)

print(f"Successfully retrieved info for {len(all_mods_from_api)} mods.")

# --- Step 6: Create "To-Do List" Grouped by Mod ---
print("\n--- Step 5: IDENTIFYING ALL MISSING VERSIONS ---")
mods_to_process = {}
V1_HEADERS = {"apikey": V1_API_KEY}
V1_API_BASE_URL = "https://api.nexusmods.com"

for mod_api_data in all_mods_from_api:
    uid = mod_api_data.get("uid")
    v1_mod_id = mod_api_data.get("modId")
    game_domain = mod_api_data.get("game", {}).get("domainName")
    if not all([uid, v1_mod_id, game_domain]): continue

    try:
        files_url = f"{V1_API_BASE_URL}/v1/games/{game_domain}/mods/{v1_mod_id}/files.json"
        files_response = requests_with_retry("GET", files_url, headers=V1_HEADERS)
        if files_response.status_code != 200: continue
        
        all_files = files_response.json()["files"]
        versions_found = {}
        for file_info in all_files:
            version = file_info.get("version")
            uploaded_timestamp = file_info.get("uploaded_timestamp", 0) 
            if version:
                if version not in versions_found:
                    versions_found[version] = {
                        "files": [],
                        "latest_upload_timestamp": 0
                    }
                versions_found[version]["files"].append(file_info)
                # Keep track of the newest file's timestamp for that version
                if uploaded_timestamp > versions_found[version]["latest_upload_timestamp"]:
                    versions_found[version]["latest_upload_timestamp"] = uploaded_timestamp
                    
        missing_versions_for_this_mod = []
        # versions_found is now a dict of dicts
        for version, version_data in versions_found.items():
            release_tag = create_release_tag(uid, mod_api_data.get('name', 'unknown'), version)
            if release_tag not in EXISTING_RELEASES:
                missing_versions_for_this_mod.append({
                    "version_to_archive": version,
                    "files_for_version": version_data["files"],
                    "upload_timestamp": version_data["latest_upload_timestamp"]
                })
                
        if missing_versions_for_this_mod:
            mods_to_process[uid] = {
                "mod_api_data": mod_api_data,
                "versions": missing_versions_for_this_mod
            }
        time.sleep(1)
    except Exception as e:
        print(f"  > ERROR checking versions for mod {v1_mod_id}: {e}")

total_new_releases = sum(len(mod['versions']) for mod in mods_to_process.values())
print(f"\nFound {len(mods_to_process)} mods with a total of {total_new_releases} new releases to create.")
if len(mods_to_process) > THROTTLE_LIMIT:
    print(f"THROTTLING: Will process up to {THROTTLE_LIMIT} mods in this run.")

# --- Step 7: Process Mods Atomically ---
print("\n--- Step 6: PROCESSING RELEASES IN THE TO-DO LIST ---")
something_changed = False
mods_to_run_this_time = list(mods_to_process.keys())[:THROTTLE_LIMIT]

for uid in mods_to_run_this_time:
    task_group = mods_to_process[uid]
    mod_api_data = task_group["mod_api_data"]
    
    for task in task_group["versions"]:
        version_to_archive = task["version_to_archive"]
        files_for_version = task["files_for_version"]
        
        v1_mod_id, mod_name, summary, description, picture_url, game_domain = (
            mod_api_data.get("modId"), mod_api_data.get("name"), mod_api_data.get("summary"),
            mod_api_data.get("description"), mod_api_data.get("pictureUrl"),
            mod_api_data.get("game", {}).get("domainName")
        )
        release_tag = create_release_tag(uid, mod_name, version_to_archive)
        print(f"--- Processing: '{mod_name}' v{version_to_archive} (Tag: {release_tag}) ---")

        changelog_markdown = ""
        try:
            print("  > Getting changelogs...")
            changelogs_url = f"{V1_API_BASE_URL}/v1/games/{game_domain}/mods/{v1_mod_id}/changelogs.json"
            changelogs_response = requests_with_retry("GET", changelogs_url, headers=V1_HEADERS)
            if changelogs_response.status_code == 200:
                all_changelogs = changelogs_response.json()
                version_changelog = all_changelogs.get(version_to_archive)
                if version_changelog:
                    print(f"  > Found changelog for version {version_to_archive}.")
                    changelog_items = "\n".join([f"- {item}" for item in version_changelog])
                    changelog_markdown = f"<details>\n<summary>Click to view Changelog for v{version_to_archive}</summary>\n\n{changelog_items}\n</details>"
                else:
                    print("  > No specific changelog found for this version.")
            else:
                print(f"  > No changelogs found (Status: {changelogs_response.status_code}).")
            time.sleep(1)
        except Exception as e:
            print(f"  > WARNING: Could not retrieve changelogs: {e}")
        
        download_jobs = []
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        if picture_url:
            file_ext = os.path.splitext(picture_url)[1] or '.jpg'
            thumb_path = os.path.join(DOWNLOADS_DIR, f"thumbnail{file_ext}")
            download_jobs.append({'url': picture_url, 'path': thumb_path, 'is_thumbnail': True, 'category': 'THUMBNAIL'})

        for file_info in files_for_version:
            category_name = file_info.get("category_name")
            if category_name in INVALID_FILE_CATEGORIES:
                print(f"    > Skipping file '{file_info['file_name']}' (Category: {category_name})")
                continue
            
            file_id, file_name = file_info["file_id"], file_info["file_name"]
            try:
                print(f"    > Getting download link for: '{file_name}'")
                link_url = f"{V1_API_BASE_URL}/v1/games/{game_domain}/mods/{v1_mod_id}/files/{file_id}/download_link.json"
                link_response = requests_with_retry("GET", link_url, headers=V1_HEADERS)
                link_response.raise_for_status()
                download_uri = link_response.json()[0]["URI"]
                
                original_filepath = os.path.join(DOWNLOADS_DIR, file_name)
                download_jobs.append({
                    'url': download_uri, 'path': original_filepath,
                    'is_thumbnail': False, 'version': version_to_archive,
                    'category': file_info.get("category_name", "UNKNOWN")
                })
                time.sleep(1)
            except Exception as e:
                print(f"    > ERROR getting download link for {file_name}: {e}")

        downloaded_files_data = []
        if download_jobs:
            print(f"  > Starting parallel download of {len(download_jobs)} files using {MAX_WORKERS} workers...")
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                results = executor.map(download_file, download_jobs)
                
                for job in results:
                    downloaded_path = job.get('downloaded_path')
                    if downloaded_path:
                        file_data = {
                            'path': downloaded_path,
                            'category': job.get('category', 'UNKNOWN')
                        }
                        
                        if not job.get('is_thumbnail'):
                            version = job.get('version')
                            name_part, extension = os.path.splitext(downloaded_path)
                            name = sanitize_filename(name_part, v1_mod_id, version)
                            new_filepath = f"{name}{extension}"
                            os.rename(downloaded_path, new_filepath)
                            file_data['path'] = new_filepath
                        
                        downloaded_files_data.append(file_data)

        if downloaded_files_data:
            try:
                print("  > Creating GitHub release...")
                release_name = f"{mod_name} - v{version_to_archive}"
                raw_description = description or summary
                release_body = format_nexus_description(raw_description)
                final_release_body = release_body
                if changelog_markdown:
                    final_release_body += "\n\n---\n\n" + changelog_markdown
                
                new_release = repo.create_git_release(tag=release_tag, name=release_name, message=final_release_body)
                
                print("  > Uploading assets...")
                release_assets_data = []
                for asset_data in downloaded_files_data:
                    asset_path = asset_data['path']
                    category = asset_data['category']

                    # Do not upload the thumbnail image as a release asset; it's only used for data.json
                    if category == 'THUMBNAIL':
                        continue

                    print(f"    - Uploading {os.path.basename(asset_path)}")
                    asset = new_release.upload_asset(asset_path)
                    
                    release_assets_data.append({
                        "name": asset.name, 
                        "url": asset.browser_download_url,
                        "category": category
                    })

                print(f"SUCCESS: Release '{release_name}' created successfully.\n")
                
                print("  > Updating local data file...")
                if uid not in indexed_known_mods:
                    indexed_known_mods[uid] = {
                        "id": uid, "modId": v1_mod_id, "name": mod_name, "game": game_domain,
                        "summary": summary, "description": format_nexus_description(description or summary),
                        "pictureUrl": picture_url, "releases": []
                    }
                
                upload_timestamp = task.get("upload_timestamp") # Get the timestamp we passed along

                release_data = {
                    "version": version_to_archive, "releaseTag": release_tag,
                    "updatedAt": new_release.created_at.isoformat(), # This is the archive date
                    "uploadTimestamp": upload_timestamp, # This is the true upload date
                    "changelog": changelog_markdown, 
                    "assets": release_assets_data
                }
                indexed_known_mods[uid]["releases"].append(release_data)
                something_changed = True
                
            except Exception as e:
                print(f"  > ERROR creating GitHub release: {e}\n")
        else:
            print("  > No files were successfully downloaded for this version. Nothing to release.\n")

        if os.path.exists(DOWNLOADS_DIR):
            shutil.rmtree(DOWNLOADS_DIR)
    
# --- Step 8: Save Data ---
if something_changed:
    print(f"\n--- Step 7: SAVING UPDATED DATA ---")
    print("  > Sorting releases for each mod by version number...")
    for mod_id in indexed_known_mods:
        if 'releases' in indexed_known_mods[mod_id]:
            indexed_known_mods[mod_id]['releases'].sort(
                key=lambda r: (parse_version(r['version']), r.get('uploadTimestamp', 0)),
                reverse=True
            )
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(indexed_known_mods, f, indent=2)
        print(f"Successfully saved {len(indexed_known_mods)} entries to {DATA_FILE}.")
    except Exception as e:
        print(f"ERROR: Could not write to {DATA_FILE}. Error: {e}")
else:
    print(f"\n--- Step 7: SAVING UPDATED DATA ---")
    print("No new releases were created. Data file remains unchanged.")

# --- Step 9: Final Summary ---
print("\n--- Step 8: SCRIPT FINISHED ---")
if not mods_to_process:
    print("All mods are up-to-date with existing releases. No new actions required.")
else:
    processed_count = min(len(mods_to_process), THROTTLE_LIMIT)
    print(f"Script processed up to {processed_count} new mods in this run.")
    remaining_mods = len(mods_to_process) - processed_count
    if remaining_mods > 0:
        print(f"{remaining_mods} more mods with new versions may be available. The next scheduled run will process them.")