# Nexus Mods Auto-Archiver

This repository contains a GitHub Action workflow to automatically track and archive mods from a specified Nexus Mods user. It periodically checks for new or updated mods and creates a new GitHub Release for each version, complete with the mod files, a formatted description, and changelogs.

This provides a personal, automated backup of your mods in case Nexus bans your ass.

## Features

-   **Automated Tracking**: Runs on a schedule to automatically find new mod versions.
-   **File Archiving**: Downloads all relevant files for a new version and attaches them to a GitHub Release.
-   **Formatted Descriptions**: Fetches the full mod description, converts it from BBCode to Markdown, and uses it as the body of the release.
-   **Changelog Integration**: If a changelog is available for a new version, it is automatically embedded in a collapsible section in the release notes.
-   **API Throttling**: To be a good API citizen and avoid rate-limiting issues, the script will only process a set number of new mods per run. This is customizable.
-   **Secure Key Management**: Your Nexus Mods API key is stored securely using GitHub Secrets and is never exposed in the code.

## How It Works

1.  **Trigger**: The GitHub Action is triggered either by a daily schedule (`cron`) or a manual dispatch.
2.  **Fetch Mod List (v2 API)**: The Python script first queries the public **v2 GraphQL API**. This API is used because it allows fetching a complete list of mods for a specific user ID without requiring authentication.
3.  **Identify New Releases**: The script compares the full list of mods and their versions against the tags of existing releases in this repository. Any mod version that does not have a corresponding release tag is added to a "to-do" list.
4.  **Process and Download (v1 API)**: For each new mod in the to-do list, the script switches to the stable **v1 REST API**, which requires an API key. It uses this API to:
    -   Fetch the detailed file list for the mod.
    -   Generate secure download links for each file.
    -   Fetch the version-specific changelog.
5.  **Create Release**: The script downloads the files, formats the description and changelogs into Markdown, and then uses the GitHub API to create a new, neatly organized release.

## Setup & Configuration

To get this running for your own use, follow these steps.

### 1. Set Up the Repository

You can either fork this repository or use it as a template.

### 2. Create the GitHub Secret

This is the most important step for authenticating with the Nexus Mods v1 API.

1.  In your repository, navigate to `Settings` > `Secrets and variables` > `Actions`.
2.  Click `New repository secret`.
3.  Set the **Name** to `NEXUSMODS_V1_API_KEY`.
4.  For the **Value**, paste your personal API key, which you can get from your [Nexus Mods account page](https://www.nexusmods.com/users/myaccount?tab=api%20access).
5.  Click `Add secret`.

### 3. Customize User

1.  Click `New repository secret`.
2.  Set the **Name** to `NEXUS_USERID`.
3.  For the **Value**, paste your Nexus userid.

## Running the Workflow

Once set up, the workflow can be run in two ways:

-   **Automatically**: The workflow is scheduled to run automatically every day. You can change the schedule by editing the `cron` value in `.github/workflows/run-tracker.yml`.
-   **Manually**:
    1.  Go to the **Actions** tab of your repository.
    2.  Select the **Nexus Mods Backup** workflow from the list on the left.
    3.  Click the **Run workflow** dropdown button on the right, and then click the green **Run workflow** button.

You can view the progress and logs for each run in the Actions tab.

## License

This project is licensed under the MIT License.
