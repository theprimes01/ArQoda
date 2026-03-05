import os
import io
import random
import string
import imghdr
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, redirect, abort, send_file
from PIL import Image, ImageDraw
import qrcode
import qrcode.constants
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 2 * 1024 * 1024))  # 2 Mo

# En-têtes de sécurité
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Décommentez si HTTPS actif
    # response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# Configuration base de données
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///qr_codes.db')

def get_db():
    """Retourne une connexion à la base de données."""
    try:
        if DATABASE_URL.startswith('sqlite'):
            import sqlite3
            db_path = DATABASE_URL.replace('sqlite:///', '')
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn
        else:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            return conn
    except Exception as e:
        # En cas d'erreur de connexion, on logge et on renvoie None
        app.logger.error(f"Erreur de connexion DB: {e}")
        return None

def init_db():
    """Crée la table des QR codes dynamiques si elle n'existe pas."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS qr_codes (
                    id SERIAL PRIMARY KEY,
                    short_code TEXT UNIQUE NOT NULL,
                    destination_url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    scan_count INTEGER DEFAULT 0
                )
            ''')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_short_code ON qr_codes(short_code)')
            conn.commit()
    except Exception as e:
        app.logger.error(f"Erreur lors de l'initialisation de la base : {e}")
        # Ne pas relancer l'exception, l'application pourra peut-être fonctionner sans base ?
        # Mais ici il vaut mieux arrêter car les QR dynamiques ne fonctionneront pas.
        # On peut choisir de relancer ou non. Pour le diagnostic, on va logger sans planter.
        # Cependant, si la base est indispensable, il faut que l'application plante.
        # On va garder le raise pour l'instant, mais avec un log.
        raise  # ← À enlever si tu veux continuer sans base (mais pas recommandé)
# Initialiser la base au démarrage de l'application
# with app.app_context():
#    init_db()

def generate_short_code(length=6):
    """Génère un code court unique."""
    chars = string.ascii_letters + string.digits
    with get_db() as conn:
        cur = conn.cursor()
        for _ in range(100):
            code = ''.join(random.choices(chars, k=length))
            try:
                cur.execute(
                    'INSERT INTO qr_codes (short_code, destination_url) VALUES (%s, %s)',
                    (code, 'placeholder')
                )
                conn.commit()
                return code
            except Exception:
                conn.rollback()
                continue
        raise Exception("Impossible de générer un code unique après 100 tentatives")

def validate_image(stream):
    """Vérifie que le flux correspond à une image valide."""
    header = stream.read(512)
    stream.seek(0)
    img_format = imghdr.what(None, header)
    if not img_format:
        return False
    return img_format in ['png', 'jpeg', 'gif']

def hex_to_rgb(hex_color):
    """Convertit une couleur hexadécimale en tuple RGB."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/create_dynamic', methods=['POST'])
def create_dynamic():
    """Crée un lien court pour QR dynamique."""
    try:
        data = request.get_json()
        url = data.get('url')
        if not url:
            return jsonify({'error': 'URL requise'}), 400

        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return jsonify({'error': 'URL invalide. Seules les URLs HTTP/HTTPS sont acceptées.'}), 400
        if len(url) > 500:
            return jsonify({'error': 'URL trop longue (max 500 caractères)'}), 400

        short_code = generate_short_code()
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                'UPDATE qr_codes SET destination_url = %s WHERE short_code = %s',
                (url, short_code)
            )
            conn.commit()
        return jsonify({'short_code': short_code})
    except Exception as e:
        app.logger.error(f"Erreur création dynamique : {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500

@app.route('/r/<short_code>')
def redirect_short(short_code):
    """Redirige vers l'URL associée au code court."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT destination_url FROM qr_codes WHERE short_code = %s', (short_code,))
            row = cur.fetchone()
            if row is None:
                abort(404)
            cur.execute('UPDATE qr_codes SET scan_count = scan_count + 1 WHERE short_code = %s', (short_code,))
            conn.commit()
        return redirect(row['destination_url'])
    except Exception as e:
        app.logger.error(f"Erreur redirection : {e}")
        abort(500)

@app.route('/api/create_round_logo', methods=['POST'])
def create_round_logo():
    """Génère un QR code à points ronds avec logo centré."""
    try:
        text = request.form.get('text')
        if not text:
            return jsonify({'error': 'Texte requis'}), 400
        if len(text) > 500:
            return jsonify({'error': 'Texte trop long (max 500 caractères)'}), 400

        fgcolor = request.form.get('fgcolor', '#000000')
        bgcolor = request.form.get('bgcolor', '#ffffff')
        dot_color = hex_to_rgb(fgcolor)
        background_color = hex_to_rgb(bgcolor)

        logo_file = request.files.get('logo')
        logo = None
        if logo_file and logo_file.filename != '':
            if not validate_image(logo_file.stream):
                return jsonify({'error': 'Format de logo non supporté'}), 400
            try:
                logo = Image.open(logo_file).convert('RGBA')
            except Exception:
                return jsonify({'error': 'Image corrompue'}), 400

        # Paramètres du QR
        module_size = 12
        dot_scale = 0.8

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            border=2
        )
        qr.add_data(text)
        qr.make(fit=True)

        matrix = qr.get_matrix()
        rows = len(matrix)
        cols = len(matrix[0])

        img_size = (cols * module_size, rows * module_size)
        img = Image.new("RGB", img_size, background_color)
        draw = ImageDraw.Draw(img)

        # Dessiner les points ronds
        dot_size = module_size * dot_scale
        offset = (module_size - dot_size) / 2

        for y in range(rows):
            for x in range(cols):
                if matrix[y][x]:
                    x1 = x * module_size + offset
                    y1 = y * module_size + offset
                    x2 = x1 + dot_size
                    y2 = y1 + dot_size
                    draw.ellipse((x1, y1, x2, y2), fill=dot_color)

        # Ajouter le logo centré (taille 25% de la largeur)
        if logo:
            logo_size = img_size[0] // 4
            logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
            pos = ((img_size[0] - logo_size) // 2, (img_size[1] - logo_size) // 2)
            if logo.mode == 'RGBA':
                img.paste(logo, pos, mask=logo.split()[3])
            else:
                img.paste(logo, pos)

        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')

    except Exception as e:
        app.logger.error(f"Erreur création round_logo : {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500

@app.route('/api/create_artistic', methods=['POST'])
def create_artistic():
    """Génère un QR code avec fusion artistique du logo."""
    try:
        text = request.form.get('text')
        if not text:
            return jsonify({'error': 'Texte requis'}), 400
        if len(text) > 500:
            return jsonify({'error': 'Texte trop long (max 500 caractères)'}), 400

        if 'logo' not in request.files:
            return jsonify({'error': 'Logo requis'}), 400
        logo_file = request.files['logo']
        if logo_file.filename == '':
            return jsonify({'error': 'Fichier logo vide'}), 400
        if not validate_image(logo_file.stream):
            return jsonify({'error': 'Format de fichier non supporté. Utilisez PNG, JPEG ou GIF.'}), 400

        try:
            logo = Image.open(logo_file).convert('RGBA')
        except Exception:
            return jsonify({'error': 'Image corrompue ou invalide'}), 400

        # Paramètres
        box_size = 10
        border = 4

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=box_size,
            border=border,
        )
        qr.add_data(text)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
        qr_width, qr_height = qr_img.size

        # Logo redimensionné à 80% de la largeur
        max_logo_size = int(qr_width * 0.8)
        logo.thumbnail((max_logo_size, max_logo_size), Image.Resampling.LANCZOS)

        pixels_qr = qr_img.load()
        logo_width, logo_height = logo.size
        x_offset = (qr_width - logo_width) // 2
        y_offset = (qr_height - logo_height) // 2

        for y in range(logo_height):
            for x in range(logo_width):
                qx = x_offset + x
                qy = y_offset + y
                if qx < 0 or qx >= qr_width or qy < 0 or qy >= qr_height:
                    continue
                r, g, b, a = logo.getpixel((x, y))
                if a == 0:
                    continue
                qr_pixel = pixels_qr[qx, qy]
                alpha = 0.5
                new_r = int((1-alpha) * qr_pixel[0] + alpha * r)
                new_g = int((1-alpha) * qr_pixel[1] + alpha * g)
                new_b = int((1-alpha) * qr_pixel[2] + alpha * b)
                pixels_qr[qx, qy] = (new_r, new_g, new_b, 255)

        img_io = io.BytesIO()
        qr_img.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')

    except Exception as e:
        app.logger.error(f"Erreur création artistique : {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'Fichier trop volumineux (max 2 Mo)'}), 413

# ------------------------------------------------------------
# Lancement (uniquement en développement)
# ------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')