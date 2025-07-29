document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const gallery = document.getElementById('mod-gallery');
    const loadingMessage = document.getElementById('loading-message');
    const searchBar = document.getElementById('search-bar');
    const sortBy = document.getElementById('sort-by');
    const themeToggleButton = document.getElementById('theme-toggle-button');
    const modalOverlay = document.getElementById('modal-overlay');
    const modalBody = document.getElementById('modal-body');
    const closeButton = document.getElementById('close-button');
    const lightboxOverlay = document.getElementById('lightbox-overlay');
    const lightboxImage = document.getElementById('lightbox-image');
    const lightboxCloseButton = document.getElementById('lightbox-close-button');

    // --- State ---
    const dataUrl = 'data.json';
    let allMods = {}; 
    let imageObserver;

    // --- Image Lazy Loading ---
    const setupIntersectionObserver = () => {
        imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const card = entry.target;
                    const thumbnailContainer = card.querySelector('.thumbnail-container');
                    const imageUrl = thumbnailContainer.dataset.src;
                    if (imageUrl) {
                        thumbnailContainer.style.backgroundImage = `url('${imageUrl}')`;
                    }
                    observer.unobserve(card); // Stop observing once loaded
                }
            });
        }, { rootMargin: '0px 0px 200px 0px' }); // Load images 200px before they enter viewport
    };

    // --- Main Logic ---
    const displayMods = (modsToDisplay) => {
        gallery.innerHTML = ''; // Clear the gallery first
        if (modsToDisplay.length === 0) {
            gallery.innerHTML = '<p>No mods match your criteria.</p>';
            return;
        }

        modsToDisplay.forEach(mod => {
            const latestRelease = mod.releases[0]; // The first release is the newest
            const modCard = document.createElement('div');
            modCard.className = 'mod-card';
            modCard.dataset.modId = mod.id;

            const summary = mod.summary ? mod.summary.replace(/"/g, '"') : 'No summary available.';
            const imageUrl = mod.pictureUrl || '';

            modCard.innerHTML = `
                <div class="summary-tooltip">${summary}</div>
                <div class="thumbnail-container" data-src="${imageUrl}"></div>
                <div class="title-overlay">${mod.name} - v${latestRelease.version}</div>
            `;
            gallery.appendChild(modCard);
            imageObserver.observe(modCard); // Observe the new card for lazy loading
        });
    };

    const updateGallery = () => {
        const searchTerm = searchBar.value.toLowerCase();
        const sortValue = sortBy.value;

        // 1. Filter mods based on search term
        const filteredMods = Object.values(allMods).filter(mod => {
            const title = mod.name.toLowerCase();
            const description = (mod.description || '').toLowerCase();
            return title.includes(searchTerm) || description.includes(searchTerm);
        });

        // 2. Sort the filtered mods
        filteredMods.sort((a, b) => {
            const releaseA = a.releases[0];
            const releaseB = b.releases[0];

            switch (sortValue) {
                case 'uploadTimestamp':
                    return (releaseB.uploadTimestamp || 0) - (releaseA.uploadTimestamp || 0);
                case 'name':
                    return a.name.localeCompare(b.name);
                case 'updatedAt': // Default case
                default:
                    return new Date(releaseB.updatedAt) - new Date(releaseA.updatedAt);
            }
        });

        // 3. Display the final list
        displayMods(filteredMods);
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
			
			const downloadableAssets = assets.filter(a => a.category !== 'THUMBNAIL');
			if (downloadableAssets.length === 0) return '';

			let html = `<h4>${title}</h4>`;
			downloadableAssets.forEach(file => {
				let versionInfo = '';
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
            setupIntersectionObserver();
            updateGallery(); // Initial render
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

    searchBar.addEventListener('input', updateGallery);
    sortBy.addEventListener('change', updateGallery);
});