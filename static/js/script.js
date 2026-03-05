document.addEventListener('DOMContentLoaded', function() {
    const dataInput = document.getElementById('data');
    const dynamicCheck = document.getElementById('dynamic');
    const fgcolorInput = document.getElementById('fgcolor');
    const bgcolorInput = document.getElementById('bgcolor');
    const logoInput = document.getElementById('logo');
    const generateRoundBtn = document.getElementById('generateRoundBtn');
    const generateArtisticBtn = document.getElementById('generateArtisticBtn');
    const downloadPngBtn = document.getElementById('downloadPngBtn');
    const canvas = document.getElementById('qrCanvas');
    const ctx = canvas.getContext('2d');
    const messageDiv = document.getElementById('message');
    const loader = document.getElementById('loader');
    const shortLinkContainer = document.getElementById('shortLinkContainer');
    const shortLinkInput = document.getElementById('shortLink');
    const copyLinkBtn = document.getElementById('copyLinkBtn');

    let currentQRBlobUrl = null;

    const MAX_LOGO_SIZE = 2 * 1024 * 1024; // 2 Mo

    function showMessage(msg, isError = false) {
        messageDiv.textContent = msg;
        messageDiv.style.color = isError ? 'red' : '#666';
    }

    function setLoading(isLoading) {
        if (isLoading) {
            loader.classList.remove('hidden');
            generateRoundBtn.disabled = true;
            generateArtisticBtn.disabled = true;
            downloadPngBtn.disabled = true;
        } else {
            loader.classList.add('hidden');
            generateRoundBtn.disabled = false;
            generateArtisticBtn.disabled = false;
        }
    }

    // Fonction commune pour appeler l'API et afficher l'image
    async function generateQR(url, formData) {
        setLoading(true);
        downloadPngBtn.disabled = true;
        shortLinkContainer.classList.add('hidden');

        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Erreur serveur');
            }

            const blob = await response.blob();
            if (currentQRBlobUrl) URL.revokeObjectURL(currentQRBlobUrl);
            currentQRBlobUrl = URL.createObjectURL(blob);

            const img = new Image();
            img.onload = function() {
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                downloadPngBtn.disabled = false;
                showMessage('QR code généré !');
            };
            img.src = currentQRBlobUrl;
        } catch (err) {
            showMessage('Erreur : ' + err.message, true);
        } finally {
            setLoading(false);
        }
    }

    // Gestionnaire pour le QR points ronds
    generateRoundBtn.addEventListener('click', async function() {
        const text = dataInput.value.trim();
        if (!text) {
            showMessage('Veuillez entrer un texte ou une URL', true);
            return;
        }

        const logoFile = logoInput.files[0];
        if (logoFile && logoFile.size > MAX_LOGO_SIZE) {
            showMessage('Le fichier logo est trop volumineux (max 2 Mo)', true);
            return;
        }

        const formData = new FormData();
        formData.append('text', text);
        formData.append('fgcolor', fgcolorInput.value);
        formData.append('bgcolor', bgcolorInput.value);
        if (logoFile) formData.append('logo', logoFile);

        // Si dynamique, on crée d'abord le lien court
        if (dynamicCheck.checked) {
            let url = text;
            if (!url.startsWith('http://') && !url.startsWith('https://')) {
                if (url.includes('.')) {
                    url = 'https://' + url;
                } else {
                    showMessage('Pour un QR dynamique, entrez une URL valide', true);
                    return;
                }
            }
            try {
                const resp = await fetch('/api/create_dynamic', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                if (!resp.ok) throw new Error('Erreur création dynamique');
                const data = await resp.json();
                const shortUrl = `${window.location.origin}/r/${data.short_code}`;
                formData.set('text', shortUrl);  // on remplace le texte par le lien court
                shortLinkInput.value = shortUrl;
                shortLinkContainer.classList.remove('hidden');
            } catch (err) {
                showMessage('Erreur : ' + err.message, true);
                return;
            }
        } else {
            shortLinkContainer.classList.add('hidden');
        }

        await generateQR('/api/create_round_logo', formData);
    });

    // Gestionnaire pour le QR artistique (fusion)
    generateArtisticBtn.addEventListener('click', async function() {
        const text = dataInput.value.trim();
        if (!text) {
            showMessage('Veuillez entrer un texte ou une URL', true);
            return;
        }

        const logoFile = logoInput.files[0];
        if (!logoFile) {
            showMessage('Pour le QR artistique, un logo est requis', true);
            return;
        }
        if (logoFile.size > MAX_LOGO_SIZE) {
            showMessage('Le fichier logo est trop volumineux (max 2 Mo)', true);
            return;
        }

        const formData = new FormData();
        formData.append('text', text);
        formData.append('logo', logoFile);

        if (dynamicCheck.checked) {
            // Même logique que ci-dessus
            let url = text;
            if (!url.startsWith('http://') && !url.startsWith('https://')) {
                if (url.includes('.')) {
                    url = 'https://' + url;
                } else {
                    showMessage('Pour un QR dynamique, entrez une URL valide', true);
                    return;
                }
            }
            try {
                const resp = await fetch('/api/create_dynamic', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                if (!resp.ok) throw new Error('Erreur création dynamique');
                const data = await resp.json();
                const shortUrl = `${window.location.origin}/r/${data.short_code}`;
                formData.set('text', shortUrl);
                shortLinkInput.value = shortUrl;
                shortLinkContainer.classList.remove('hidden');
            } catch (err) {
                showMessage('Erreur : ' + err.message, true);
                return;
            }
        } else {
            shortLinkContainer.classList.add('hidden');
        }

        await generateQR('/api/create_artistic', formData);
    });

    downloadPngBtn.addEventListener('click', function() {
        if (currentQRBlobUrl) {
            const link = document.createElement('a');
            link.href = currentQRBlobUrl;
            link.download = 'qrcode.png';
            link.click();
        }
    });

    copyLinkBtn.addEventListener('click', function() {
        shortLinkInput.select();
        document.execCommand('copy');
        showMessage('Lien copié !');
    });
});