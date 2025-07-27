document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const gallery = document.getElementById('mod-gallery');
    const loadingMessage = document.getElementById('loading-message');
    const searchBar = document.getElementById('search-bar');
    const themeToggleButton = document.getElementById('theme-toggle-button');
    const modalOverlay = document.getElementById('modal-overlay');
    const modalBody = document.getElementById('modal-body');
    const closeButton = document.getElementById('close-button');
    const lightboxOverlay = document.getElementById('lightbox-overlay');
    const lightboxImage = document.getElementById('lightbox-image');
    const lightboxCloseButton = document.getElementById('lightbox-close-button');

    // --- Configuration ---
    const repoOwner = 'gs-oar';
    const repoName = 'NexusBackup';

    const dataUrl = 'data.json';
    
    // The data.json is an object where keys are mod UIDs
    let allMods = {}; 

    // --- Main Render Function ---
    // Renders the main gallery view, showing only the latest version of each mod.
    const renderGallery = (modsToRender) => {
        gallery.innerHTML = ''; // Clear the gallery first
        if (Object.keys(modsToRender).length === 0) {
            gallery.innerHTML = '<p>No mods match your criteria.</p>';
            return;
        }

        // Sort the mods themselves by the date of their latest release
        const sortedMods = Object.values(modsToRender).sort((a, b) => {
            return new Date(a.releases[0].updatedAt) - new Date(b.releases[0].updatedAt);
        }).reverse(); // Newest first
		
        sortedMods.forEach(mod => {
            const latestRelease = mod.releases[0]; // The first release is the newest
            const modCard = document.createElement('div');
            modCard.className = 'mod-card';
            modCard.dataset.modId = mod.id; // The main mod UID

            const summary = mod.summary ? mod.summary.replace(/"/g, '"') : 'No summary available.';

            modCard.innerHTML = `
                <div class="summary-tooltip">${summary}</div>
                <div class="thumbnail-container" style="background-image: url('${mod.pictureUrl || ''}')"></div>
                <div class="title-overlay">${mod.name} - v${latestRelease.version}</div>
            `;
            gallery.appendChild(modCard);
        });
    };

    // --- Modal Functions ---
	const openModal = (modId) => {
		const mod = allMods[modId];
		if (!mod) return;

		// --- Determine Current Files ---
		const latestMainRelease = mod.releases[0];
		const latestOptionalFiles = {};

		// Iterate through ALL releases (newest to oldest) to find the latest version of each optional file.
		mod.releases.forEach(release => {
			if (!release.assets) return;
			release.assets.forEach(asset => {
				// Consider OPTIONAL, UPDATE, etc. as optional. Exclude MAIN and ARCHIVED.
				const isOptional = asset.category && !['MAIN', 'OLD_VERSION', 'ARCHIVED', 'THUMBNAIL'].includes(asset.category);
				if (isOptional) {
					// Since we iterate newest to oldest, the first time we see a filename, it's the latest version.
					if (!latestOptionalFiles[asset.name]) {
						latestOptionalFiles[asset.name] = { ...asset, originalVersion: release.version };
					}
				}
			});
		});

		// Helper to build a list of download links from an array of assets
		const buildAssetsHtml = (assets, title) => {
			if (!assets || assets.length === 0) return '';
			
			// Filter out thumbnail "assets" which are just for data, not download
			const downloadableAssets = assets.filter(a => a.category !== 'THUMBNAIL');
			if (downloadableAssets.length === 0) return '';

			let html = `<h4>${title}</h4>`;
			downloadableAssets.forEach(file => {
				let versionInfo = '';
				// Add version info to optional files to avoid confusion
				if (title.toLowerCase().includes('optional')) {
					versionInfo = ` <span class="file-version">(for v${file.originalVersion})</span>`;
				}
				html += `<a href="${file.url}" target="_blank">${file.name}</a>${versionInfo}`;
			});
			return html;
		};

		const mainFiles = latestMainRelease.assets.filter(a => a.category === 'MAIN');
		const mainFilesHtml = buildAssetsHtml(mainFiles, 'Main Files');
		const optionalFilesHtml = buildAssetsHtml(Object.values(latestOptionalFiles), 'Optional Files & Patches');

		// --- Build Version History ---
		let olderVersionsHtml = '';
		if (mod.releases.length > 0) {
			olderVersionsHtml = `<details class="version-history">
				<summary>View Full Version History (${mod.releases.length})</summary>`;
			mod.releases.forEach(release => {
				// In history, we show ALL files for that specific version release
				const allVersionFiles = buildAssetsHtml(release.assets, 'Downloads for this version');
				olderVersionsHtml += `
					<div class="older-version">
						<h3>Version ${release.version}</h3>
						${release.changelog || ''}
						${allVersionFiles || 'No files recorded for this version.'}
					</div>`;
			});
			olderVersionsHtml += `</details>`;
		}
		
		const renderedDescription = marked.parse(mod.description || 'No description provided.');
		const nexusLinkHtml = `<a href="https://www.nexusmods.com/${mod.game}/mods/${mod.modId}" class="view-on-nexus" target="_blank">View on Nexus Mods</a>`;

		modalBody.innerHTML = `
			<h2>${mod.name} - v${latestMainRelease.version}</h2>
			<div class="modal-layout">
				<div class="modal-left-column">
					${mod.pictureUrl ? `<img src="${mod.pictureUrl}" alt="${mod.name}" class="modal-thumbnail">` : ''}
					${nexusLinkHtml}
					<div class="assets">
						${mainFilesHtml}
						${optionalFilesHtml}
					</div>
				</div>
				<div class="modal-right-column">
					<div class="description">${renderedDescription}</div>
					${latestMainRelease.changelog || ''}
					${olderVersionsHtml}
				</div>
			</div>
		`;
		
		const modalThumbnail = modalBody.querySelector('.modal-thumbnail');
		if (modalThumbnail) {
			modalThumbnail.addEventListener('click', () => openLightbox(modalThumbnail.src));
		}
		modalOverlay.classList.remove('hidden');
	};

    const closeModal = () => modalOverlay.classList.add('hidden');
    const openLightbox = (imageUrl) => { lightboxImage.src = imageUrl; lightboxOverlay.classList.remove('hidden'); };
    const closeLightbox = () => lightboxOverlay.classList.add('hidden');
    
    // --- Initial Data Fetch ---
    fetch(dataUrl)
        .then(response => {
            if (!response.ok) { throw new Error('data.json not found or invalid.'); }
            return response.json();
        })
        .then(data => {
            loadingMessage.style.display = 'none';
            allMods = data;
            renderGallery(allMods);
		})
        .catch(error => {
            console.error('Error fetching data.json:', error);
            loadingMessage.textContent = 'Failed to load mod data. The data.json file may be missing or invalid. Please run the archiver action.';
        });

    // --- Theme Toggle Logic ---
    const applyTheme = (theme) => {
        if (theme === 'light') {
            document.body.classList.add('light-mode');
            themeToggleButton.textContent = '🌙';
        } else {
            document.body.classList.remove('light-mode');
            themeToggleButton.textContent = '☀️';
        }
        localStorage.setItem('theme', theme);
    };
    themeToggleButton.addEventListener('click', () => {
        const newTheme = document.body.classList.contains('light-mode') ? 'dark' : 'light';
        applyTheme(newTheme);
    });
    const savedTheme = localStorage.getItem('theme') || 'dark';
    applyTheme(savedTheme);

    // --- Event Listeners ---
    gallery.addEventListener('click', (e) => {
        const card = e.target.closest('.mod-card');
        if (card) openModal(card.dataset.modId);
    });
    closeButton.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (e) => { if (e.target === modalOverlay) closeModal(); });
    lightboxCloseButton.addEventListener('click', closeLightbox);
    lightboxOverlay.addEventListener('click', (e) => { if (e.target === lightboxOverlay) closeLightbox(); });

    searchBar.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        const filteredMods = {};
        for (const modId in allMods) {
            const mod = allMods[modId];
            const title = mod.name.toLowerCase();
            const description = (mod.description || '').toLowerCase();
            if (title.includes(searchTerm) || description.includes(searchTerm)) {
                filteredMods[modId] = mod;
            }
        }
        renderGallery(filteredMods);
    });
});