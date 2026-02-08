import streamlit as st
import pandas as pd
import io
import plotly.express as px
import re
import time
import plotly.graph_objects as go
from streamlit_option_menu import option_menu
from streamlit_gsheets import GSheetsConnection
import streamlit_authenticator as stauth
from difflib import get_close_matches
from datetime import datetime
from datetime import date
from fpdf import FPDF
from sqlalchemy import create_engine, text

def refresh_sidebar():
            # Cette fonction ne fait rien, mais son appel via 'on_change'
            # force Streamlit à re-exécuter toute l'application (et donc le compteur)
                pass  


st.set_page_config(page_title="Mes Budgets",page_icon="💰", layout="wide",initial_sidebar_state="collapsed")


if "user" not in st.session_state:
    st.session_state["user"] = None

@st.cache_resource
def get_engine():
    """Crée et met en cache l'engine SQL pour toute la durée de session"""
    return create_engine(st.secrets["connections"]["postgresql"]["url"])

# On crée l'unique instance
engine = get_engine()

# Définis ta version ici centralisée
APP_VERSION = "V2.0.0"

# Injection de CSS pour coller le texte en bas à gauche
st.markdown(
    f"""
    <style>
    .version-footer {{
        position: fixed;
        top: 50px;
        right: 20px;
        color: #7f8c8d;
        font-size: 12px;
        z-index: 100;
    }}
    </style>
    <div class="version-footer">Mes budgets app {APP_VERSION}</div>
    """,
    unsafe_allow_html=True
)



def supprimer_transaction_neon(row, user):
    try:
           
        with engine.begin() as conn:
            query = text("""
                DELETE FROM transactions 
                WHERE date = :date 
                AND nom = :nom 
                AND montant = :montant 
                AND utilisateur = :utilisateur
            """)
            
            # On convertit explicitement pour éviter le bug np.float64
            parametres = {
                "date": row['date'],
                "nom": str(row['nom']),
                "montant": float(row['montant']), # <--- C'est ici que ça se joue !
                "utilisateur": str(user)
            }
            
            conn.execute(query, parametres)
        return True
    except Exception as e:
        st.error(f"Erreur suppression Neon : {e}")
        return False

def generer_pdf_tricount(nom_groupe, df_groupe, transferts, total, sujet=None):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    W = 190 

    # --- Titre ---
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(W, 10, f"{nom_groupe}", ln=True, align='C')
    
    if total > 0:
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(W, 10, f"Total des depenses du groupe : {total:.2f} EUR", ln=True, align='C')
    
    pdf.ln(10)

    # --- Section Remboursements (Le coeur du sujet) ---
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(W, 10, "BILAN DES TRANSFERTS :", ln=True)
    pdf.ln(2)

    if transferts:
        for t in transferts:
            # Logique de couleur et texte si c'est un PDF individuel
            if sujet:
                if t['de'] == sujet: # C'est une dette
                    pdf.set_text_color(200, 0, 0) # Rouge
                    texte = f"[-] DOIT DONNER {t['montant']:.2f} EUR a {t['a']}"
                else: # C'est un reçu
                    pdf.set_text_color(0, 128, 0) # Vert
                    texte = f"[+] VA RECEVOIR {t['montant']:.2f} EUR de {t['de']}"
            else:
                # Format simple pour le PDF Global
                pdf.set_text_color(0, 0, 0)
                texte = f"> {t['de']} doit donner {t['montant']:.2f} EUR a {t['a']}"
            
            pdf.set_font("Helvetica", "B" if sujet else "", 11)
            pdf.multi_cell(W, 8, texte, align='L')
            pdf.ln(1)
    else:
        pdf.set_font("Helvetica", "I", 11)
        pdf.cell(W, 10, "Aucun transfert a effectuer.", ln=True)

    pdf.set_text_color(0, 0, 0) # Reset couleur
    pdf.ln(10)

    # --- Historique (Tableau) ---
    # On ne l'affiche que si le tableau n'est pas vide (pour le global)
    if not df_groupe.empty and total > 0:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(W, 10, "Rappel de l'historique :", ln=True)
        pdf.set_font("Helvetica", "", 10)
        
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(30, 8, "date", border=1, fill=True)
        pdf.cell(70, 8, "Libelle", border=1, fill=True)
        pdf.cell(50, 8, "Paye par", border=1, fill=True)
        pdf.cell(40, 8, "montant", border=1, fill=True, ln=True)

        for _, row in df_groupe.iterrows():
            if float(str(row['montant']).replace(',', '.')) > 0:
                pdf.cell(30, 8, str(row['date']), border=1)
                libelle_propre = str(row['libellé'])[:35] 
                pdf.cell(70, 8, libelle_propre, border=1)
                pdf.cell(50, 8, str(row['payé_par']), border=1)
                pdf.cell(40, 8, f"{float(str(row['montant']).replace(',', '.')):.2f} EUR", border=1, ln=True)
    
    return pdf.output()



def mettre_a_jour_transaction_tricount_neon(id_transaction, nouveaux_donnees):
    try:
           
        with engine.begin() as conn:
            query = text("""
                UPDATE tricount 
                SET libellé = :lib, montant = :mont, payé_par = :payeur, pour_qui = :repart
                WHERE id = :id
            """)
            conn.execute(query, {
                "lib": nouveaux_donnees['libellé'],
                "mont": nouveaux_donnees['montant'],
                "payeur": nouveaux_donnees['payé_par'],
                "repart": nouveaux_donnees['pour_qui'],
                "id": id_transaction
            })
        return True
    except Exception as e:
        st.error(f"Erreur SQL Update : {e}")
        return False


def charger_tricount_neon(user):
    try:
           
        query = text("SELECT * FROM tricount WHERE utilisateur = :u ORDER BY date DESC")
        
        with engine.connect() as sql_conn:
            df = pd.read_sql(query, sql_conn, params={"u": user})
        
        if df is None or df.empty:
            # On définit bien l'id ici aussi pour la structure
            return pd.DataFrame(columns=["id", "date", "libellé", "payé_par", "pour_qui", "montant", "utilisateur"])
        
        # Mapping pour l'UI (on garde 'id' en minuscule car c'est notre clé technique)
        mapping = {
            'libellé': 'libellé',
            'payé_par': 'payé_par',
            'pour_qui': 'pour_qui'
        }
        df = df.rename(columns=mapping)
        return df
    except Exception as e:
        st.error(f"Erreur lecture : {e}")
        return pd.DataFrame()


def sauvegarder_transaction_tricount_neon(nouvelle_ligne_dict):
    try:
           
        
        # On s'assure que 'id' n'est pas dans le dictionnaire pour laisser SQL gérer
        if 'id' in nouvelle_ligne_dict:
            del nouvelle_ligne_dict['id']
            
        new_row_df = pd.DataFrame([nouvelle_ligne_dict])
        new_row_df.columns = [c.lower() for c in new_row_df.columns]
        
        with engine.begin() as conn:
            new_row_df.to_sql('tricount', conn, if_exists='append', index=False)
        return True
    except Exception as e:
        st.error(f"Erreur sauvegarde : {e}")
        return False
    

def supprimer_transaction_tricount_neon(id_a_supprimer):
    try:
           
        with engine.begin() as conn:
            # On vise l'ID précis
            conn.execute(text("DELETE FROM tricount WHERE id = :id"), {"id": id_a_supprimer})
        return True
    except Exception as e:
        st.error(f"Erreur suppression : {e}")
        return False



def relancer_avec_succes(message="Action réussie !"):
    st.toast(message, icon="✅")
    time.sleep(0.8)
    st.rerun()


def sauvegarder_notes_neon(texte, user):
    try:
           
        
        # Requête "ON CONFLICT" : si l'utilisateur existe déjà, on met à jour son texte
        # Sinon, on insère une nouvelle ligne.
        query = text("""
            INSERT INTO notes (utilisateur, texte) 
            VALUES (:u, :t)
            ON CONFLICT (utilisateur) 
            DO UPdate SET texte = EXCLUDED.texte;
        """)
        
        with engine.begin() as conn_sql:
            conn_sql.execute(query, {"u": user, "t": texte})
        return True
    except Exception as e:
        st.error(f"Erreur de sauvegarde Neon : {e}")
        return False

def charger_notes_neon(user):
    try:
           
        query = text("SELECT texte FROM notes WHERE utilisateur = :u")
        
        with engine.connect() as conn_sql:
            result = conn_sql.execute(query, {"u": user}).fetchone()
            
        if result:
            note = result[0]
            return note if (note and str(note) != "nan") else ""
        return ""
    except Exception as e:
        # On ne bloque pas l'app si la note n'existe pas encore
        return ""
    

def charger_budgets_complets_neon(user, mois, compte):
    try:
           
        # On filtre directement à la source
        query = text("""
            SELECT * FROM budgets 
            WHERE utilisateur = :u AND mois = :m AND compte = :c
        """)
        
        with engine.connect() as sql_conn:
            df = pd.read_sql(query, sql_conn, params={"u": user, "m": mois, "c": compte})
        
        if df.empty:
            return pd.DataFrame(columns=['utilisateur', 'mois', 'compte', 'type', 'nom', 'somme'])
        
        # On remet les majuscules si ton code UI en a besoin
        df.columns = [c.capitalize() if c != 'utilisateur' else 'utilisateur' for c in df.columns]
        return df
    except Exception as e:
        return pd.DataFrame(columns=['utilisateur', 'mois', 'compte', 'Type', 'nom', 'Somme'])

def enregistrer_ligne_budget_neon(user, mois, compte, categorie, montant):
    try:
           
        
        with engine.begin() as conn_sql:
            # 1. Supprimer l'ancienne valeur pour cette catégorie précise
            delete_query = text("""
                DELETE FROM budgets 
                WHERE utilisateur = :u AND mois = :m AND compte = :c AND nom = :n
            """)
            conn_sql.execute(delete_query, {"u": user, "m": mois, "c": compte, "n": categorie})

            # 2. Ajout de la nouvelle ligne si montant > 0
            if montant > 0:
                insert_query = text("""
                    INSERT INTO budgets (utilisateur, mois, compte, type, nom, somme)
                    VALUES (:u, :m, :c, :t, :n, :s)
                """)
                conn_sql.execute(insert_query, {
                    "u": user, "m": mois, "c": compte, 
                    "t": 'categorie', "n": categorie, "s": montant
                })
        
        return True
    except Exception as e:
        st.error(f"Erreur SQL Budgets : {e}")
        return False



def trouver_categorie_similaire_neon(nom_transaction, user, seuil=0.6):
    """
    Cherche une catégorie suggérée dans la base Neon en fonction de l'historique de l'utilisateur.
    """
    try:
           
        
        # On ne récupère que les noms et catégories uniques de l'utilisateur
        # C'est beaucoup plus léger que de charger tout le DataFrame
        query = text("""
            SELECT DISTINCT nom, categorie 
            FROM transactions 
            WHERE user = :u
        """)
        
        with engine.connect() as conn_sql:
            df_historique = pd.read_sql(query, conn_sql, params={"u": user})

        if df_historique.empty:
            return None, None
        
        # On récupère la liste des noms connus (on s'assure de la casse)
        noms_connus = df_historique['nom'].unique().tolist()
        
        # Utilisation de difflib (comme dans ta fonction originale)
        matches = get_close_matches(nom_transaction, noms_connus, n=1, cutoff=seuil)
        
        if matches:
            nom_proche = matches[0]
            # On récupère la catégorie associée
            categorie_suggeree = df_historique[df_historique['nom'] == nom_proche]['categorie'].iloc[0]
            return categorie_suggeree, nom_proche
        
        return None, None

    except Exception as e:
        st.error(f"Erreur suggestion catégorie : {e}")
        return None, None

def preparer_credentials_neon():
    try:
           
        with engine.connect() as conn:
            # On récupère Tous
            df_users = pd.read_sql('SELECT username, name, password, email FROM users', conn)
        
        # 2. Transformer le DataFrame en dictionnaire structuré pour l'authenticator
        credentials = {'usernames': {}}
        
        for _, row in df_users.iterrows():
            credentials['usernames'][row['username']] = {
                'name': row['name'],
                'password': row['password'], # Doit être le hash
                'email': row['email']
            }
        return credentials
    except Exception as e:
        st.error(f"Erreur credentials : {e}")
        return {'usernames': {}}

# --- DANS TON SCRIPT PRINCIPAL ---
credentials = preparer_credentials_neon()

authenticator = stauth.Authenticate(
    credentials,  # Ce dictionnaire contient maintenant la clé 'usernames'
    st.secrets['cookie']['name'],
    st.secrets['cookie']['key'],
    st.secrets['cookie']['expiry_days']
)



@st.cache_data(ttl=1800)

def charger_config_neon(user):
    try:
           
        
        # Plus besoin de guillemets doubles ici !
        query = text("SELECT * FROM configuration WHERE utilisateur = :u")
        
        with engine.connect() as sql_conn:
            # On s'assure que user est bien une chaîne propre
            u_clean = str(user).strip().lower()
            df_cfg = pd.read_sql(query, sql_conn, params={"u": u_clean})

        if df_cfg.empty:
            return {}

        # On force tout en minuscules pour ne pas se soucier des majuscules de Neon
        df_cfg.columns = [c.lower() for c in df_cfg.columns]
        
        config_dict = {}
        for _, row in df_cfg.iterrows():
            # On utilise les clés en minuscules (car on a fait .lower() juste au dessus)
            nom_compte = str(row.get("compte", "")).strip()
            
            if nom_compte:
                config_dict[nom_compte] = {
                    "Solde": float(row.get("solde", 0)),
                    "Groupe": str(row.get("groupe", "Personnel")),
                    "Objectif": float(row.get("objectif", 0)),
                    "Couleur": str(row.get("couleur", "#3498db"))
                }
        return config_dict

    except Exception as e:
        st.error(f"Erreur config Neon : {e}")
        return {}


@st.cache_data(ttl=1800)
def charger_donnees(user):
    try:
           
        # On teste 'utilisateur' d'abord, sinon '"user"'
        query = text('SELECT * FROM transactions WHERE utilisateur = :u')
        
        with engine.connect() as sql_conn:
            df = pd.read_sql(query, sql_conn, params={"u": str(user).strip()})

        if df.empty:
            # Structure de secours SANS ACCENT pour correspondre à Neon
            return pd.DataFrame(columns=['date', 'nom', 'montant', 'categorie', 'compte', 'utilisateur', 'annee', 'mois'])

        # 1. Normalisation forcée : Tout en minuscule, sans espaces, pas d'accents manuels
        df.columns = [c.lower().strip() for c in df.columns]
        
        # 2. Gestion spécifique des noms de colonnes
        # Si Neon renvoie 'user', on le renomme en 'utilisateur' pour ton code
        if 'user' in df.columns:
            df = df.rename(columns={'user': 'utilisateur'})
            
        # 3. Sécurité Dates et Années
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            # On crée 'annee' (sans accent) si elle n'existe pas
            if 'annee' not in df.columns and 'année' not in df.columns:
                df['annee'] = df['date'].dt.year
        
        return df

    except Exception as e:
        st.error(f"Erreur SQL lors du chargement : {e}")
        return pd.DataFrame(columns=['date', 'nom', 'montant', 'categorie', 'compte', 'utilisateur', 'annee', 'mois'])

    
    
def sauvegarder_config_neon(config_dict, user):
    """
    Sauvegarde TOUTE la configuration d'un coup (Soldes, groupes, Objectifs).
    C'est la seule fonction dont tu as besoin.
    """
    try:
           
        
        rows = []
        for compte, data in config_dict.items():
            rows.append({
                'utilisateur': user.lower(),
                'compte': compte,
                'solde': float(data.get('Solde', 0)),
                'groupe': str(data.get('Groupe', 'Personnel')), # Attention Majuscule 'G'
                'objectif': float(data.get('Objectif', 0)),
                'couleur': str(data.get('Couleur', '#3498db'))
            })
        
        with engine.begin() as conn_sql:
            for row_data in rows:
                query = text("""
                    INSERT INTO configuration (utilisateur, compte, solde, groupe, objectif, couleur)
                    VALUES (:utilisateur, :compte, :solde, :groupe, :objectif, :couleur)
                    ON CONFLICT (utilisateur, compte) 
                    DO UPDATE SET 
                        solde = EXCLUDED.solde,
                        groupe = EXCLUDED.groupe,
                        objectif = EXCLUDED.objectif,
                        couleur = EXCLUDED.couleur;
                """)
                conn_sql.execute(query, row_data)
        
        return True
        
    except Exception as e:
        st.error(f"Erreur sauvegarde Neon : {e}")
        return False


def clear_input_new_cat():
    st.session_state.input_new_cat = ""

def afficher_ligne_compacte(row, couleur_montant, prefixe=""):
    # 1. Sécurité pour la date (Compatible GSheets 'date' et Neon 'date')
    date_val = row.get('date') or row.get('date')
    if pd.isnull(date_val):
        date_str = "??/??"
    else:
        try:
            date_str = date_val.strftime('%d/%m')
        except AttributeError:
            date_str = str(date_val)[:5]

    # 2. Préparation des données texte avec FIX EMOJI
    cat_val = row.get('categorie') or row.get('categorie')
    cat = str(cat_val) if pd.notna(cat_val) else "À catégoriser ❓"
    
    raw_ico = cat[:1] if cat else "💰"
    ico = raw_ico + "\uFE0F"
    
    if any(x in cat for x in ["Virement :", "Transfert Interne"]) and "🤝" not in cat:
        ico = "🔄\uFE0F"
    
    # 3. Sécurité pour le texte (Support GSheets/Neon)
    nom_val = row.get('nom') or row.get('nom')
    nom_propre = str(nom_val).replace('"', "&quot;") if pd.notna(nom_val) else "Sans nom"
    
    compte_val = row.get('compte') or row.get('compte')
    compte_str = str(compte_val) if pd.notna(compte_val) else "Inconnu"
    
    # 4. Sécurité pour le montant
    montant_val = row.get('montant') or row.get('montant')
    try:
        valeur_montant = abs(float(montant_val))
        montant_str = f"{prefixe}{valeur_montant:.2f}€"
    except (ValueError, TypeError):
        montant_str = "0.00€"

    # --- PARTIE GRAPHIQUE HTML ---
    html_content = f"""
<div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #f0f2f6; width: 100%;">
    <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
        <span style="font-size: 0.9rem; flex-shrink: 0;">{ico}</span>
        <div style="min-width: 0;">
            <p style="margin: 0; font-weight: bold; font-size: 0.7rem; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: white;">
                {nom_propre}
            </p>
            <p style="margin: 0; font-size: 0.6rem; color: #7f8c8d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                {date_str} • <i>{compte_str}</i>
            </p>
        </div>
    </div>
    <div style="text-align: right; flex-shrink: 0; margin-left: 10px;">
        <p style="margin: 0; color: {couleur_montant}; font-weight: bold; font-size: 0.7rem; white-space: nowrap;">
            {montant_str}
        </p>
    </div>
</div>"""
    
    st.markdown(html_content, unsafe_allow_html=True)
    





def update_couleur_compte_neon(nom_compte, user):
    # 1. On identifie la clé du widget Color Picker
    cle_picker_actuel = f"cp_{nom_compte}"
    
    if cle_picker_actuel in st.session_state:
        # 2. On synchronise le dictionnaire local avec les widgets
        if "config_groupes" in st.session_state:
            for c in st.session_state.config_groupes:
                cle_p = f"cp_{c}"
                if cle_p in st.session_state:
                    # On met à jour la couleur dans le dictionnaire en mémoire
                    st.session_state.config_groupes[c]["Couleur"] = st.session_state[cle_p]
                elif "Couleur" not in st.session_state.config_groupes[c]:
                    # Couleur par défaut si rien n'est trouvé
                    st.session_state.config_groupes[c]["Couleur"] = "#1f77b4"

            # 3. Sauvegarde immédiate dans Neon
            # Ici, on utilise la version SQL qui est instantanée
            succes = sauvegarder_config_neon(st.session_state.config_groupes, user)
            
            if succes:
                st.toast(f"🎨 Couleur de '{nom_compte}' synchronisée sur Neon !")
            else:
                st.error("Erreur lors de la synchronisation de la couleur.")


# --- 5. DESIGN (SORTI DU IF POUR TOUJOURS S'APPLIQUER) ---
st.markdown("""
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 0rem; }
        header[data-testid="stHeader"] { background: rgba(0,0,0,0); }
    </style>
""", unsafe_allow_html=True)

# --- 2. DICTIONNAIRES ET CONSTANTES ---
CORRESPONDANCE = {
    "date": ["date", "date opération", "date de valeur", "Effective date", "date op", "date val", "Le", "date de comptabilisation","date operation", "date"],
    "nom": ["nom", "Libelle simplifie", "libellé", "Description", "Transaction", "libellé de l'opération", "Détails", "Objet", "Type"],
    "montant": ["montant", "montant(EUROS)", "Valeur", "Amount", "Prix", "montant net", "Somme"],
    "Debit": ["Debit", "Débit"],
    "Credit": ["Credit", "Crédit"]
}

nomS_mois = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]


@st.cache_data(ttl=600)
def charger_memoire_neon(user):
    try:
           
        # On récupère les associations nom -> Catégorie enregistrées par l'utilisateur
        query = text("SELECT nom_clean, categorie FROM memoire WHERE user = :u")
        
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"u": user})
            
        # On transforme le DF en dictionnaire { 'nom_CLEAN': 'Catégorie' }
        return dict(zip(df['nom_clean'], df['categorie']))
    except Exception:
        return {}



def categoriser(nom_operation, montant=0, compte_actuel=None, ligne_complete=None):
    n_brut = str(nom_operation).upper()
    n_clean = simplifier_nom_definitif(n_brut)
    
    # 1. MÉMOIRE (Priorité absolue via Neon)
    # On récupère l'user depuis le session_state
    user = st.session_state.get("user")
    if user:
        # On utilise une fonction charger_memoire_neon que nous allons définir
        memoire = charger_memoire_neon(user)
        if n_clean in memoire: 
            return memoire[n_clean]

    # 2. SCAN COMPLET DE LA LIGNE
    if ligne_complete is not None:
        texte_integral = n_brut + " " + str(ligne_complete.get('Informations complementaires', '')).upper()
    else:
        texte_integral = n_brut

    # 3. LES compteS ET PROCHES
    mes_comptes = ["LIVRET A", "LDDS", "compte CHEQUES", "COMMUN"]
    proches = ["MARYLINE FONTA", "AURORE FONTA", "LEBARBIER THEO", "LEBARBIER DIDIER"]

    # --- ÉTAPE A : DÉTECTION DES TRANSFERTS INTERNES (🔄) ---
    # On cherche le mot "VERS" suivi d'un de tes comptes [cite: 2, 5]
    
    if "VERS" in texte_integral:
        if "LIVRET A" in texte_integral: return "🔄 Virement : CCP vers Livret A"
        if "compte CHEQUES" in texte_integral or "CCP" in texte_integral: return "🔄 Virement : Livret A vers CCP"
        if any(c in texte_integral for c in mes_comptes): return "🔄 Transfert Interne"

    # --- ÉTAPE B : DÉTECTION DES PROCHES (🤝) ---
    # Si on est ici, c'est que ce n'est pas un transfert "VERS" un compte
    if montant > 0 and any(p in n_brut for p in proches):
        return "🤝 Virements Reçus"

    # --- ÉTAPE C : SALAIRES ET REVENUS ---
    if any(s in texte_integral for s in ["SARL LES GOURMANDISES", "FRANCE TRAVAIL", "JEFF DE BRUGES"]):
        return "💰 Salaire"

    # ... (Le reste de tes catégories habituelles)

    # --- 5. TOUTES TES CATÉGORIES (Liste intégrale) ---
    categorieS_MOTS_CLES = {
        "💰 Salaire": ["MELTED", "JEFF DB", "FRANCE TRAVAIL", "POLE EMPLOI", "SARL", "JEFF DE BRUGES"],
        "🏥 Remboursements": ["NOSTRUMCARE", "AMELI", "CPAM", "REMBOURSEMENT", "SANTÉ", "FAUSTINE BOJUC"],
        "👫 compte Commun": ["A FONTA AUDE OU LEBARBIER THEO", "AUDE FONTATHEO LEBARBIE", "VERSEMENT COMMUN", "VIREMENT COMMUN"],
        "🤝 Virements Reçus": proches,
        "📱 Abonnements": ["NETFLIX", "SPOTIFY", "DISNEY PLUS", "AMAZON PRIME", "YOUTUBE PREMIUM", "ORANGE", "GOOGLE PLAY", "GOOGLE ONE", "AMZ DIGITAL", "TWITCH"],
        "🛒 Alimentation": ["CARREFOUR", "AUCHAN", "MONOPRIX", "CASINO", "SUPER", "PICARD", "BIOCOOP", "MARCHE", "BOULANGERIE", "RESTAURANT", "BAR", "MCDO", "SUBWAY", "INTERMARCHE", "LECLERC", "AUTOGRILL", "PROZIS", "CIAO BELLA"],
        "🛍️ Shopping": ["AMAZON", "FNAC", "DARTY", "CULTURA", "ZARA", "H&M", "KIABI", "KLARNA"],
        "👕 Habillement": ["VETEMENTS", "CHAUSSURES", "MODE", "CELIO", "JULES", "ASOS"],
        "⚖️ Impôts": ["IMPOTS", "TRESOR PUBLIC", "DGFIP"],
        "🏦 Frais Bancaires": ["COTISATION BANCAIRE","COTISATIONS BANCAIRES", "FRAIS BANCAIRES", "COTISATION ESSENTIEL"],
        "🏠 Assurance Habitation": ["PACIFICA", "MMA", "MAIF", "MACIF"],
        "🎮 Jeux vidéos": ["SONY PLAYSTATION", "NINTENDO", "STEAM", "EPIC GAMES", "INSTANT GAMING"],
        "🩺 Mutuelle": ["MUTUELLE", "HARMONIE", "MGEN", "NOSTRUM CARE"],
        "💊 Pharmacie": ["PHARMACIE", "MÉNARD", "PHARMA"],
        "👨‍⚕️ Médecin/Santé": ["MEDECIN", "DENTISTE", "DOCTOLIB"],
        "🔑 Loyer": ["LOYER", "AGENCE IMMOBILIERE", "JASON MOLINER"],
        "🔨 Bricolage": ["CASTORAMA", "LEROY", "BRICO DEPOT", "IKEA"],
        "🚌 Transports": ["RATP", "SNCF", "TCL", "ORIZO"],
        "⛽ Carburant": ["TOTAL", "BP", "ESSENCE", "SHELL", "ESSOF", "CERTAS", "STATION"],
        "🚗 Auto": ["CREDIT AUTO", "GARAGE", "REPARATION", "AUTO"],
        "💸 Virements envoyé": ["VIREMENT A", "VIREMENT INSTANTANE", "VIR SEPA"],
        "🏧 Retraits": ["RETRAIT DAB", "RETRAIT GAB"],
        "🌐 Web/Énergie": ["FREE", "SFR", "BOUYGUES", "EDF", "ENGIE"],
    }
    
    for cat, mots in categorieS_MOTS_CLES.items():
        if any(m in n_brut for m in mots):
            return cat
    
    return "💰 Autres Revenus" if montant > 0 else "❓ Autre"


# --- FONCTIONS DE GESTION DES CATÉGORIES ---

def charger_categories_neon(user):
    """Renvoie TOUTES les catégories (Défaut + Perso) SANS filtrer les masquées."""
    defaut = [
        "💰 Salaire", "🏥 Remboursements", "🤝 Virements Reçus", "👫 compte Commun",
        "📱 Abonnements", "🛒 Alimentation", "🛍️ Shopping", "👕 Habillement", 
        "⚖️ Impôts", "🏦 Frais Bancaires", "🏠 Assurance Habitation", "🎮 Jeux vidéos",
        "🩺 Mutuelle", "💊 Pharmacie", "👨‍⚕️ Médecin/Santé", "🔑 Loyer", 
        "🔨 Bricolage", "🚌 Transports", "⛽ Carburant", "🚗 Auto", 
        "💸 Virements envoyé", "🏧 Retraits", "🌐 Web/Énergie", 
        "🔄 Virement : Livret A vers CCP", "🔄 Virement : CCP vers Livret A", "❓ Autre"
    ]
    if not user: return sorted(defaut)

    try:
        # On ne récupère QUE les catégories perso (sans s'occuper des masquées ici)
           
        with engine.connect() as conn:
            res_perso = conn.execute(
                text("SELECT nom FROM categories WHERE utilisateur = :u"), {"u": user}
            ).fetchall()
            perso = [r[0] for r in res_perso]
        
        return sorted(list(set(defaut + perso)))
    except Exception as e:
        return sorted(defaut)

def charger_categories_neon_masquees(user):
    """Lit les catégories masquées dans Neon pour l'utilisateur."""
    try:
           
        # Utilise 'utilisateur' pour être cohérent avec ta fonction de sauvegarde
        query = text('SELECT nom FROM categories_masquees WHERE utilisateur = :u')
        
        with engine.connect() as connection:
            result = connection.execute(query, {"u": user}).fetchall()
        return [r[0] for r in result]
    except Exception as e:
        return []

def charger_categories_neon_visibles(user):
    """Renvoie la liste filtrée pour les menus déroulants du tableau."""
    # On récupère TOUT le référentiel
    totale = charger_categories_neon(user) 
    # On récupère les masquées
    masquees = charger_categories_neon_masquees(user)
    # On ne garde que ce qui n'est pas masqué
    return [c for c in totale if c not in masquees]

def sauvegarder_preference_masquage_neon(user, liste_a_masquer):
    try:
           
        with engine.begin() as conn:
            # Nettoyage de l'existant
            conn.execute(
                text("DELETE FROM categories_masquees WHERE utilisateur = :u"), {"u": user}
            )
            # Insertion des nouvelles préférences
            if liste_a_masquer:
                for cat in liste_a_masquer:
                    conn.execute(
                        text("INSERT INTO categories_masquees (nom, utilisateur) VALUES (:n, :u)"),
                        {"n": cat, "u": user}
                    )
        return True
    except Exception as e:
        st.error(f"Erreur sauvegarde masquage : {e}")
        return False

def sauvegarder_nouvelle_categorie_neon(nouvelle_cat, user):
    try:
           
        with engine.begin() as conn:
            # Le SQL gère lui-même le doublon si tu as mis une contrainte UNIQUE(nom, utilisateur)
            conn.execute(text("""
                INSERT INTO categories (nom, utilisateur) 
                VALUES (:n, :u)
                ON CONFLICT (nom, utilisateur) DO NOTHING
            """), {"n": nouvelle_cat, "u": user})
        
        # Rafraîchissement immédiat du session_state
        st.session_state.LISTE_categorieS_COMPLETE = charger_categories_neon(user)
        return True
    except Exception as e:
        st.error(f"Erreur lors de l'ajout : {e}")
        return False


if "user" in st.session_state:
    LISTE_categorieS_COMPLETE = charger_categories_neon_visibles(st.session_state.user)
else:
    # Optionnel : une liste par défaut si personne n'est connecté
    LISTE_categorieS_COMPLETE = []
# --- 3. TOUTES LES FONCTIONS ---


@st.cache_data(ttl=1800)

def charger_memoire_neon(user):
    try:
           
        # On ne récupère que ce qui appartient à l'utilisateur
        query = text("SELECT nom, categorie FROM memoire WHERE user = :u")
        
        with engine.connect() as conn:
            df_memo = pd.read_sql(query, conn, params={"u": user})
            
        if df_memo.empty:
            return {}
            
        # On transforme en dictionnaire { 'nom': 'Catégorie' }
        return dict(zip(df_memo['nom'], df_memo['categorie']))
    except Exception:
        return {}

def sauvegarder_apprentissage_batch_neon(liste_transactions, user):
    try:
           
        
        with engine.begin() as conn_sql:
            for nom_ope, categorie in liste_transactions:
                nom_clean = simplifier_nom_definitif(nom_ope)
                
                # Le SQL "UPSERT" : si le nom existe déjà pour cet utilisateur, on met à jour la catégorie
                query = text("""
                    INSERT INTO memoire (utilisateur, nom, categorie)
                    VALUES (:u, :n, :c)
                    ON CONFLICT (utilisateur, nom) 
                    DO UPDATE SET categorie = EXCLUDED.categorie
                """)
                
                conn_sql.execute(query, {
                    "u": user,
                    "n": nom_clean,
                    "c": categorie
                })
        return True
    except Exception as e:
        st.error(f"Erreur apprentissage Neon : {e}")
        return False

@st.cache_data(ttl=1800)

def charger_tout_le_theme_neon(user):
    try:
           
        query = text('SELECT element, couleur FROM theme WHERE "user" = :u')
        
        with engine.connect() as conn_sql:
            df_user = pd.read_sql(query, conn_sql, params={"u": user})
        
        if df_user.empty:
            return {}
            
        # On transforme en dictionnaire { "Background": "linear-gradient...", "Bouton": "#FF0000" }
        return dict(zip(df_user['element'], df_user['couleur']))
    except Exception as e:
        return {}

# 1. On charge le thème uniquement s'il n'est pas déjà en mémoire
if "user_theme" not in st.session_state:
    try:
        # On utilise notre nouvelle fonction SQL performante
        # Elle récupère un dictionnaire : {'Background': 'linear-gradient...', 'Bouton': '#hex'}
        theme_dict = charger_tout_le_theme_neon(st.session_state["user"])
        
        # On stocke le dictionnaire (plus pratique qu'un DataFrame pour le CSS)
        st.session_state.user_theme = theme_dict
        
    except Exception as e:
        st.session_state.user_theme = {}
        st.error(f"Erreur chargement design : {e}")

@st.cache_data(ttl=1800)

# Nouvelle fonction charger_couleur qui ne lit plus GSheets mais la session :
def charger_couleur(type_couleur="Couleur", default="#222222"):
    try:
        # On utilise la fonction qui a le cache @st.cache_data
        theme_dict = charger_tout_le_theme_neon(st.session_state["user"])
        
        # On récupère la couleur dans le dictionnaire en mémoire (0 requête API)
        return theme_dict.get(type_couleur, default)
    except:
        return default

def sauvegarder_plusieurs_couleurs_neon(nouveaux_reglages):
    """
    Sauvegarde en lot les éléments du thème (fond, boutons, etc.) sur Neon.
    nouveaux_reglages : dict {'Background': '#hex', 'Bouton': '#hex'}
    """
    try:
           
        user = st.session_state["user"]
        
        with engine.begin() as conn_sql:
            for element, hex_color in nouveaux_reglages.items():
                # On utilise ON CONFLICT pour mettre à jour la couleur si l'élément existe déjà
                query = text("""
                    INSERT INTO theme ("user", element, couleur)
                    VALUES (:u, :e, :c)
                    ON CONFLICT ("user", element) 
                    DO UPdate SET couleur = EXCLUDED.couleur
                """)
                conn_sql.execute(query, {"u": user, "e": element, "c": hex_color})
        
        # On vide le cache spécifique du thème pour forcer le rafraîchissement visuel
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erreur sauvegarde thème Neon : {e}")
        return False


@st.cache_data(ttl=1800)

def charger_groupes(user):
    """
    Récupère la liste des groupes uniques de l'utilisateur.
    Garantit que tes groupes sauvegardés le 24/12 sont bien chargés.
    """
    try:
        # On appelle la fonction Neon que nous avons créée précédemment
        config = charger_config_neon(user) 
        
        if config:
            # On extrait les groupes définis pour chaque compte
            groupes = list(set(v.get("groupe", "personnel") for v in config.values()))
            # On retourne la liste triée sans les valeurs "nan" ou vides
            return sorted([g for g in groupes if g and str(g) != "nan"])
        
        return ["Personnel"]
    except Exception:
        return ["Personnel"]
    
    





def clean_montant_physique(valeur):
    if pd.isna(valeur) or valeur == "": return 0.0
    s = str(valeur).replace('\xa0', '').replace(' ', '').replace('€', '').replace('$', '')
    if ',' in s and '.' in s: s = s.replace(',', '')
    elif ',' in s: s = s.replace(',', '.')
    try: return float(s)
    except: return 0.0




def sauvegarder_donnees_neon(nouveau_df, user=None):
    try:
           
        u_final = user or st.session_state.get("user")
        if not u_final:
            st.error("❌ Utilisateur non détecté.")
            return False

        df_to_save = nouveau_df.copy()
        df_to_save["utilisateur"] = str(u_final).strip()
        
        # SÉCURITÉ : On s'assure que les dates sont JUSTE des dates (pas d'heures cachées)
        df_to_save['date'] = pd.to_datetime(df_to_save['date'], dayfirst=True, errors='coerce').dt.date
        df_to_save = df_to_save.dropna(subset=['date'])

        # SÉCURITÉ : On nettoie les espaces dans les noms (souvent cause de faux doublons)
        df_to_save['nom'] = df_to_save['nom'].astype(str).str.strip()

        for col in ['nom', 'categorie', 'compte', 'mois']:
            if col in df_to_save.columns:
                df_to_save[col] = df_to_save[col].fillna("Inconnu")

        with engine.begin() as conn_sql:
            for _, row in df_to_save.iterrows():
                query = text("""
                    INSERT INTO transactions (date, nom, montant, categorie, compte, utilisateur, mois, année)
                    VALUES (:date, :nom, :montant, :categorie, :compte, :utilisateur, :mois, :année)
                    ON CONFLICT (date, nom, montant, utilisateur)
                    DO UPDATE SET
                        categorie = EXCLUDED.categorie,
                        mois = EXCLUDED.mois,
                        compte = EXCLUDED.compte,
                        année = EXCLUDED.année
                """)
                conn_sql.execute(query, row.to_dict())
        return True
    except Exception as e:
        st.error(f"Erreur de sauvegarde Neon : {e}")
        return False


@st.cache_data(ttl=1800)
def charger_previsions_neon():
    if "user" not in st.session_state or not st.session_state["user"]:
        return pd.DataFrame(columns=["date", "nom", "montant", "categorie", "compte", "mois", "annee", "utilisateur"])
    try:
           
        user = st.session_state["user"]
        
        # On ne récupère que les prévisions de l'utilisateur actif
        query = text('SELECT * FROM previsions WHERE LOWER("utilisateur") = LOWER(:u)')
        
        with engine.connect() as conn_sql:
            df = pd.read_sql(query, conn_sql, params={"u": user})
        
        if df.empty:
            return pd.DataFrame(columns=["date", "nom", "montant", "categorie", "compte", "mois", "annee", "utilisateur"])
        
        # Typage propre pour Pandas
        df["date"] = pd.to_datetime(df["date"], errors='coerce')
        df["montant"] = pd.to_numeric(df["montant"], errors='coerce').fillna(0.0)
        
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement Neon : {e}") # Ajoute ça pour debugger !
        return pd.DataFrame(columns=["date", "nom", "montant", "categorie", "compte", "mois", "annee", "utilisateur"])

def sauvegarder_previsions_neon(df_prev, user):
    """
    Sauvegarde les prévisions sur Neon en remplaçant l'existant pour cet utilisateur.
    """
    try:
           
        
        # 1. Préparation des données (on s'assure que le user est correct et colonnes en minuscules)
        df_to_save = df_prev.copy()
        df_to_save["utilisateur"] = user.lower()
        df_to_save.columns = [c.lower() for c in df_to_save.columns]
        
        # Formatage de la date pour SQL
        if 'date' in df_to_save.columns:
            df_to_save['date'] = pd.to_datetime(df_to_save['date']).dt.strftime('%Y-%m-%d')

        with engine.begin() as conn_sql:
            # 2. On nettoie uniquement TES anciennes prévisions
            conn_sql.execute(text('DELETE FROM previsions WHERE "utilisateur" = :u'), {"u": user.lower()})
            
            # 3. On insère le nouveau bloc
            if not df_to_save.empty:
                df_to_save.to_sql('previsions', conn_sql, if_exists='append', index=False)
        
        st.success("🔮 Prévisions synchronisées sur Neon !")
        return True
        
    except Exception as e:
        st.error(f"❌ Erreur de sauvegarde Neon : {e}")
        return False


def simplifier_nom_definitif(nom):
    """
    Nettoie le libellé pour ne garder que l'essentiel.
    Ex: 'ACHAT CB CARREFOUR 12345' -> 'CARREFOUR'
    """
    if not isinstance(nom, str): 
        return str(nom)
    
    nom = nom.upper()
    
    # 1. Supprime les numéros de factures, de virements et IDs (Neon-Ready)
    nom = re.sub(r'(FAC|REF|NUM|ID|PRLV|VIREMENT|VIR)\s*[:.\-]?\s*[0-9A-Z]{3,}', '', nom)
    
    # 2. Supprime les dates (ex: 12/01/24)
    nom = re.sub(r'\d{2}[\./]\d{2}([\./]\d{2,4})?', '', nom)
    
    # 3. Nettoyage des termes bancaires inutiles
    mots_a_virer = ["ACHAT CB", "ACHAT", "CB", "CARTE", "VERSEMENT", "CHEQUE", "SEPA", "PRÉLÈV"]
    for m in mots_a_virer:
        nom = nom.replace(m, "")
    
    # 4. Nettoyage des caractères spéciaux et espaces superflus
    # On transforme les symboles en espaces puis on 're-join' pour supprimer les espaces doubles
    nom_clean = ' '.join(re.sub(r'[\*\-\/#]', ' ', nom).split()).strip()
    
    return nom_clean or "AUTRE"


def calculer_evolution_comptes(df_transactions, soldes_initiaux, noms_mois):
    # Initialisation
    evolution = {str(k).strip().upper(): [] for k in soldes_initiaux.keys()}
    soldes_courants = {str(k).strip().upper(): float(v) for k, v in soldes_initiaux.items()}
    config = st.session_state.get('config_groupes', {})

    for mois in noms_mois:
        df_mois = df_transactions[df_transactions['mois'] == mois]
        virements_reels = df_mois[df_mois['categorie'].str.contains("🔄", na=False)]

        for _, ligne in df_mois.iterrows():
            montant = float(ligne.get('montant', 0))
            compte_source = str(ligne.get('compte', '')).strip().upper()
            cat = str(ligne.get('categorie', '')).upper()

            # 1. Action sur le compte réel
            if compte_source in soldes_courants:
                soldes_courants[compte_source] += montant
            
            # 2. Simulation de la contrepartie (Logique restaurée)
            if "🔄" in cat:
                # On retrouve le groupe du compte source
                nom_source_config = next((k for k in config.keys() if k.strip().upper() == compte_source), None)
                if nom_source_config:
                    groupe_source = config[nom_source_config].get("Groupe")
                    
                    for nom_dest_config, cfg_dest in config.items():
                        nom_dest_upper = str(nom_dest_config).strip().upper()
                        
                        # Condition de groupe + Nom différent + Présent dans le texte
                        if cfg_dest.get("Groupe") == groupe_source and nom_dest_upper != compte_source:
                            mots = [m for m in nom_dest_upper.split() if len(m) > 2]
                            if mots and any(m in cat for m in mots):
                                
                                # Anti-doublon
                                deja_present = not virements_reels[
                                    (virements_reels['compte'].str.upper() == nom_dest_upper) & 
                                    (abs(virements_reels['montant'] - (-montant)) < 0.1)
                                ].empty
                                
                                if not deja_present and nom_dest_upper in soldes_courants:
                                    soldes_courants[nom_dest_upper] += (-montant)
                                break
        
        # Enregistrement mensuel
        for c in soldes_courants:
            evolution[c].append(soldes_courants[c])
            
    return evolution


def actualiser_donnees_neon():
    """
    Force le rechargement complet depuis Neon.
    Utile si tu as modifié des données directement dans la console SQL ou sur un autre appareil.
    """
    # 1. On vide TOUT le cache de Streamlit
    # Cela force charger_config_neon(), charger_tout_le_theme_neon(), etc. à refaire une requête SQL
    st.cache_data.clear()
    
    # 2. Nettoyage ciblé du session_state
    cles_a_supprimer = ["df", "df_prev", "config_groupes", "user_theme", "LISTE_categorieS_COMPLETE"]
    
    for cle in cles_a_supprimer:
        if cle in st.session_state:
            del st.session_state[cle]
            
    # 3. Message de succès personnalisé
    st.toast("🚀 Données synchronisées avec Neon !")
    
    # 4. Relance l'application pour appliquer les changements (Thème, groupes, etc.)
    # Note : relancer_avec_succes() est ta fonction personnalisée de rerun
    relancer_avec_succes()











# --- 2. LOGIQUE D'AFFICHAGE (CONNEXION / INSCRIPTION) ---
if not st.session_state.get("authentication_status"):
    # On crée les onglets
    tabs = st.tabs(["🔐 Connexion", "👤 Créer un compte", "🔑 Reset Mot de passe"])
    
    with tabs[0]:
        try:
            # 1. On tente le login
            authenticator.login(location='main')
            
            # --- AJOUT ICI ---
            # Si authenticator a réussi, il a créé 'username'. 
            # On le copie dans 'user' pour ton code.
            if st.session_state.get("authentication_status"):
                st.session_state["user"] = st.session_state["username"]
        except Exception as e:
            st.error(f"Erreur technique : {e}")
        
        # 2. LA CORRECTION : Si le statut vient de passer à True, on force le rafraîchissement
        # Cela évite de devoir cliquer une deuxième fois pour voir l'app
        if st.session_state.get("authentication_status"):
            relancer_avec_succes()

        # 3. Gestion des messages d'erreur (inchangée)
        if st.session_state.get("authentication_status") is False:
            st.error('utilisateur ou mot de passe incorrect')
        elif st.session_state.get("authentication_status") is None:
            st.info("Veuillez entrer vos identifiants.")
            
    with tabs[1]:
        with st.form("formulaire_inscription"):
            nouveau_user = st.text_input("Identifiant (user)")
            nouveau_nom = st.text_input("nom complet")
            nouveau_email = st.text_input("Email")
            nouveau_pass = st.text_input("Mot de passe", type="password")
            bouton_creer = st.form_submit_button("Créer mon compte")
            
            if bouton_creer:
                if nouveau_user and nouveau_pass and nouveau_email:
                    try:
                           
                        hash_pass = stauth.Hasher.hash(nouveau_pass)
                        
                        with engine.begin() as conn_sql:
                            # Vérification directe en SQL
                            existe = conn_sql.execute(
                                text("SELECT 1 FROM users WHERE user = :u"), {"u": nouveau_user}
                            ).fetchone()
                            
                            if existe:
                                st.error("Cet identifiant existe déjà.")
                            else:
                                conn_sql.execute(text("""
                                    INSERT INTO users (user, name, password, email)
                                    VALUES (:u, :n, :p, :e)
                                """), {"u": nouveau_user, "n": nouveau_nom, "p": hash_pass, "e": nouveau_email})
                                
                                st.success(f"✅ compte '{nouveau_user}' créé !")
                                time.sleep(2)
                                st.rerun()
                    except Exception as e:
                        st.error(f"Erreur Neon : {e}")
    
    with tabs[2]:
        with st.form("form_forgot_custom"):
            user_to_reset = st.text_input("Identifiant").strip().lower()
            email_to_verify = st.text_input("Email enregistré").strip().lower()
            new_pass_1 = st.text_input("Nouveau mot de passe", type="password")
            new_pass_2 = st.text_input("Confirmez", type="password")
            submit_reset = st.form_submit_button("Réinitialiser")

            if submit_reset:
                if new_pass_1 != new_pass_2:
                    st.error("Les mots de passe ne correspondent pas.")
                else:
                    try:
                           
                        hash_nouveau = stauth.Hasher.hash(new_pass_1)
                        
                        with engine.begin() as conn_sql:
                            # On vérifie si le couple user/email est bon et on met à jour
                            result = conn_sql.execute(text("""
                                UPdate users 
                                SET password = :p 
                                WHERE LOWER(user) = :u AND LOWER(email) = :e
                            """), {"p": hash_nouveau, "u": user_to_reset, "e": email_to_verify})
                            
                            if result.rowcount > 0:
                                st.success("✅ Mot de passe mis à jour !")
                                st.balloons()
                            else:
                                st.error("❌ Identifiant ou Email incorrect.")
                    except Exception as e:
                        st.error(f"Erreur : {e}")



else:
    # On s'assure que 'user' est bien synchronisé avec 'username' de l'authenticator
    if "user" not in st.session_state or st.session_state["user"] is None:
        st.session_state["user"] = st.session_state.get("username")

    current_user = st.session_state.get("user")
    
    if "last_logged_user" not in st.session_state:
        st.session_state.last_logged_user = current_user

    # Si le compte actuel est différent du dernier compte enregistré dans cette session
    if st.session_state.last_logged_user != current_user:
        st.cache_data.clear()  # ON VIDE TOUT LE CACHE GLOBAL
        # On supprime les variables de données pour forcer le rechargement
        for key in ['df', 'config_groupes', 'df_f']:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state.last_logged_user = current_user
        relancer_avec_succes() # On relance pour charger les bonnes données
        
    # --- BARRE LATÉRALE ---
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.get('name', 'utilisateur')}")
        
        # On ne met pas de "if" devant le logout car la bibliothèque gère l'état
        authenticator.logout('Déconnexion', 'sidebar')

        # Si après l'appel, le statut est tombé à None, on nettoie TOUT
        if st.session_state.get("authentication_status") is None:
            st.cache_data.clear()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            relancer_avec_succes()

        # --- ASTUCE : ON VERIFIE SI L'AUTHENTIFICATION VIENT DE TOMBER ---
        if st.session_state.get("authentication_status") is None:
            # On vide tout avant de repartir
            st.cache_data.clear()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            relancer_avec_succes()



    # --- RESTE DE TON APPLICATION ---
    # C'est ici que tes groupes et ton dégradé de fond s'affichent
   # Encore plus petit et discret
    

    # --- 1. CONFIGURATION ---


    

    st.markdown('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">', unsafe_allow_html=True)

    # --- 3. VARIABLES DE TRAVAIL (Initialisation par défaut) ---
   
    df_f = pd.DataFrame()
    df_dash = pd.DataFrame()
    df_reel = pd.DataFrame()
    solde_global = 0.0
    obj = 0.0
    s_init = 0.0
    cps = []

    



# --- INITIALISATION DU SESSION STATE ---
if st.session_state.get("authentication_status"):
    # Utilise 'username' qui est la clé standard de streamlit-authenticator
    user_actuel = st.session_state.get("username")
    
    if user_actuel:
        # 1. Sécurité : Initialisation immédiate des objets pour éviter les AttributeError
        if 'df' not in st.session_state:
            st.session_state.df = pd.DataFrame()
        if 'config_groupes' not in st.session_state:
            st.session_state.config_groupes = {}
        if 'LISTE_categorieS_COMPLETE' not in st.session_state:
            st.session_state.LISTE_categorieS_COMPLETE = []

        # 2. Chargement réel depuis Neon (seulement si le DataFrame est vide)
        if st.session_state.df.empty:
            data = charger_donnees(user_actuel) 
            st.session_state.df = data if data is not None else pd.DataFrame()
        
        # 3. Chargement de la configuration des groupeS
        if not st.session_state.config_groupes:
            config = charger_config_neon(user_actuel)
            st.session_state.config_groupes = config if config else {}

        # 4. Construction de la liste des groupes pour les menus
        if 'groupes_liste' not in st.session_state:
            if st.session_state.config_groupes:
                st.session_state.groupes_liste = sorted(list(set(
                    v.get("Groupe", "Personnel") for v in st.session_state.config_groupes.values()
                ))) # Correction : 'Groupe' avec Majuscule pour matcher ta fonction charger_config_neon
            else:
                st.session_state.groupes_liste = ["Personnel"]

        # 5. Bloc-notes et Mémoire (Migration Neon)
        if 'memoire' not in st.session_state:
            st.session_state.memoire = charger_memoire_neon(user_actuel)

        if "bloc_notes_content" not in st.session_state:
            st.session_state.bloc_notes_content = charger_notes_neon(user_actuel)
        
        if "dernier_import_stats" not in st.session_state:
            st.session_state.dernier_import_stats = None
            

            # 3. Détection et fusion des comptes
            # On regarde les comptes dans le DF (filtré par user) et dans la config (filtrée par user)
            comptes_avec_data = st.session_state.df["compte"].unique().tolist() if not st.session_state.df.empty else []
            comptes_configures = list(st.session_state.config_groupes.keys())
            
            # On convertit chaque élément 'c' en string pour éviter le conflit float/str
            comptes_detectes = sorted(list(set(str(c) for c in (comptes_avec_data + comptes_configures) if c)))
            
            # 4. Attribution de couleurs par défaut pour les comptes non configurés
            for c in comptes_detectes:
                if c not in st.session_state.config_groupes:
                    st.session_state.config_groupes[c] = {
                        "Couleur": "#1f77b4", 
                        "groupe": "Personnel", 
                        "Solde": 0.0
                    }

    # Récupération de la couleur de fond (vos préférences sauvegardées)
    bg_color_saved = st.session_state.get('page_bg_color', "#0e1117")

    df_h = st.session_state.df.copy()
   # 1. On sécurise le DataFrame
    df_h.columns = [c.strip().lower() for c in df_h.columns]

    # 2. On s'assure que cps est bien une liste (pour .isin)
    if not isinstance(cps, list):
        cps = [cps]

    # 3. Maintenant, la ligne 1731 ne peut plus rater 'compte'
    if "compte" in df_h.columns:
        df_temp_filtre = df_h[df_h["compte"].isin(cps)]
    else:
        st.error(f"La colonne 'compte' est absente. Colonnes réelles : {list(df_h.columns)}")
        df_temp_filtre = pd.DataFrame()

    # --- 5. SIDEBAR ---
    with st.sidebar:
        st.title("🛡️ Configuration")

        # --- 1. RÉGLAGES DU THÈME ---
        st.subheader("🎨 Réglages du Thème")

        # On charge les couleurs actuelles (via le cache)
        # Note : On ne sauvegarde PLUS après chaque picker pour éviter l'erreur 429
        col_patri = st.color_picker("Évolution Patrimoine", charger_couleur("color_patrimoine", "#1f77b4"))
        col_jauge = st.color_picker("Jauge Objectif", charger_couleur("color_jauge", "#f1c40f"))
        col_dep = st.color_picker("Barres des dépenses", charger_couleur("color_depenses", "#e74c3c"))
        col_rev = st.color_picker("Aires des Revenus", charger_couleur("color_revenus", "#2ecc71"))
        col_perf_dep = st.color_picker("Aires des Dépenses", charger_couleur("color_perf_dep", "#e74c3c"))
        col_epargne = st.color_picker("Aires de l'Épargne", charger_couleur("color_epargne", "#3498db"))
        col_Icones = charger_couleur("color_icones", "#15C98D")
        bg_color = charger_couleur("color_background", "#012523")
        c_primary = charger_couleur("color_primary", "#2ecc71")
        c_bg_sec = charger_couleur("color_bg_sec", "#013a36")



        # --- 2. COULEURS DES compteS (MODIFIÉ POUR PERSISTANCE) ---
        st.subheader("🏦 Couleurs des comptes")
        
        comptes_actifs = []
        if not st.session_state.df.empty:
            comptes_actifs = st.session_state.df["compte"].unique().tolist()
            
        # On force tout en texte (str) et on ignore les valeurs None/NaN avant de trier
        tous_les_comptes = sorted(list(set(str(c) for c in list(st.session_state.config_groupes.keys()) + comptes_actifs if pd.notna(c))))

        for c in tous_les_comptes:
            if c not in st.session_state.config_groupes:
                st.session_state.config_groupes[c] = {"Couleur": "#1f77b4", "groupe": "Personnel", "Solde": 0.0}
            
            # 1. On récupère la valeur brute
            current_val = st.session_state.config_groupes[c].get("Couleur", "#1f77b4")
            
            # 2. SÉCURISATION : Si la valeur est NaN ou invalide, on force une couleur par défaut
            # pd.isna() gère les valeurs 'nan' issues de Pandas/Excel/GSheets
            if pd.isna(current_val) or not str(current_val).startswith("#"):
                current_val = "#1f77b4"
            
            # 3. Utilisation du picker avec la valeur nettoyée
            # Le key=f"cp_{c}" permet de maintenir l'état du widget
            nouvelle_coul = st.color_picker(f"Couleur : {c}", current_val, key=f"cp_{c}")
            
            # 4. Mise à jour immédiate du session_state
            st.session_state.config_groupes[c]["Couleur"] = nouvelle_coul

        # --- 3. BOUTON DE SAUVEGARDE UNIQUE (ANTI-QUOTA) ---
        st.write("")
        if st.button("💾 Enregistrer les réglages", width='stretch'):
            with st.spinner("Synchronisation en cours..."):
                # On regroupe tout dans un dictionnaire
                batch_couleurs = {
                    "color_patrimoine": col_patri,
                    "color_jauge": col_jauge,
                    "color_depenses": col_dep,
                    "color_revenus": col_rev,
                    "color_perf_dep": col_perf_dep,
                    "color_epargne": col_epargne,
                    "color_icones": col_Icones,
                    "color_background": bg_color,
                    "color_primary": c_primary,
                    "color_bg_sec": c_bg_sec,
                    
                }
                
                if sauvegarder_plusieurs_couleurs_neon(batch_couleurs):
                    # Les couleurs de comptes sont déjà dans st.session_state.config_groupes
                    sauvegarder_config_neon(st.session_state.config_groupes, st.session_state["user"])
                    st.success("Configuration sauvegardée !")
                    time.sleep(1)
                    relancer_avec_succes()

        
        if st.button("🔄 Actualiser les données", width='stretch'):
            actualiser_donnees_neon()

    # 1. Toujours initialiser la session en haut de ton script
    if 'menu_option' not in st.session_state:
        st.session_state.menu_option = 0

    # 2. Le menu doit être défini SANS indentation (tout à gauche)
    # Pour qu'il soit créé à chaque rechargement
    selected = option_menu(
        menu_title=None,
        options=["Analyses", "Prévisionnel", "Gérer", "Importer", "comptes", "Tricount"],
        icons=["bar-chart-line-fill", "calendar-range-fill", "table", "file-earmark-spreadsheet-fill", "credit-card-fill","bi-cash-stack"], 
        key='menu_main',
        default_index=st.session_state.menu_option,
        orientation="horizontal",
        styles={
            "container": {
                "padding": "0px !important", 
                "background-color": f"{bg_color} !important",
                "border": "none !important",
                "margin": "0px !important",
                "max-width": "100% !important"
                },
                "icon": {"color": col_Icones, "font-size": "25px"},
                "nav-link": {
                    "font-size": "15px",
                    "background-color": "transparent !important",
                    "font-weight": "bold",
                    "border-radius": "15px",
                    "width": "100px",
                    "height": "80px",
                    "display": "flex",
                    "flex-direction": "column",
                    "align-items": "center",
                },
                "nav-link-selected": {
                    "background-color": "rgba(255, 255, 255, 0.1) !important", 
                    "font-weight": "bold",
                },
            }
        )
    

    # 3. Maintenant 'selected' existe forcément, on peut l'utiliser
    # Fais attention que cette ligne ne soit PAS plus indentée que le menu au-dessus
    index_actuel = ["Analyses", "Prévisionnel", "Gérer", "Importer", "comptes","Tricount"].index(selected)
    st.session_state.menu_option = index_actuel

    
        # --- 2. BLOC CSS UNIQUE (Version corrigée : Visibilité Sidebar & Menu) ---
    st.markdown(f"""
    <style>
                
                
        /* 1. VARIABLES RACINES ET FOND GLOBAL */
        :root {{
            --background-color: {bg_color} !important;
            /* CORRECTION : On utilise c_bg_sec pour la variable secondaire */
            --secondary-background-color: {c_bg_sec} !important;
            --primary-color: {c_primary} !important;
        }}

        html, body, .stApp {{
            background-color: {bg_color} !important;
            background: {bg_color} !important;
        }}

        /* 2. TRANSPARENCE DU CONTENU PRINCIPAL */
        /* On cible spécifiquement le container de droite pour ne pas impacter la sidebar */
        [data-testid="stMainViewContainer"] [data-testid="stVerticalBlock"], 
        [data-testid="stMainViewContainer"] [data-testid="stHorizontalBlock"],
        [data-testid="stMainViewContainer"] [data-testid="stCustomComponentV1"] {{
            background-color: transparent !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }}

        /* 3. CIBLAGE DU MENU (.menu) - SUPPRESSION BANDES SOMBRES */
        div.menu, 
        .menu[data-v-5af006b8], 
        .container-xxl, 
        .nav-justified {{
            background-color: {bg_color} !important;
            background: {bg_color} !important;
            border: none !important;
            box-shadow: none !important;
        }}

        iframe[title="streamlit_option_menu.option_menu"] {{
            background-color: transparent !important;
            width: 100% !important;
            border: none !important;
        }}

        /* 4. FIX SIDEBAR (Forçage de la visibilité et de la couleur) */
        [data-testid="stSidebar"] {{
            background-color: {c_bg_sec} !important;
            visibility: visible !important;
            display: block !important;
        }}
        
        [data-testid="stSidebarContent"] {{
            background-color: {c_bg_sec} !important;
        }}
        
        /* Contenu interne de la sidebar */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
            background-color: transparent !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            opacity: 1 !important;
        }}

        /* 5. BOUTONS ET ACCENTS */
        button[kind="primary"] {{
            background-color: {c_primary} !important;
            border-color: {c_primary} !important;
            color: white !important;
        }}

        /* 6. MARGES DE PAGE ET HEADER */
        .block-container {{
            padding-top: 1rem !important;
            padding-bottom: 0rem !important;
            max-width: 100% !important;
        }}

        /* On cache le header proprement sans bloquer la sidebar */
        [data-testid="stHeader"] {{
            background-color: transparent !important;
            background: transparent !important;
        }}

        
    </style>
    """, unsafe_allow_html=True)



    


    st.markdown("""
    <style>
        /* 1. Supprimer l'espace vide tout en haut de la page */
        .block-container {
            padding-top: 0rem !important;
            padding-bottom: 0rem !important;
            margin-top: -20px !important; /* Remonte le contenu vers le haut */
        }

        /* 2. Masquer la barre d'outils Streamlit si nécessaire pour gagner de la place */
        [data-testid="stHeader"] {
            background: transparent !important;
            height: 0px !important;
        }

        /* 3. S'assurer que le conteneur du menu n'est pas bridé en hauteur */
        div[data-testid="stCustomComponentV1"] {
            overflow: visible !important;
            height: auto !important;
            min-height: 100px !important; /* Ajuste selon la taille de tes carrés */
        }
    </style>
    """, unsafe_allow_html=True)



    if selected == "Analyses":
            # --- INITIALISATION DE LA PERSISTENCE ---
            if "filtre_profil_index" not in st.session_state:
                st.session_state.filtre_profil_index = 0  # Par défaut : "Tous"
            # --- PRÉPARATION DES DONNÉES ---
            if st.session_state.df.empty:
                df_h = pd.DataFrame(columns=["date", "nom", "montant", "categorie", "compte", "mois", "année"])
                liste_annees = [pd.Timestamp.now().year]
            else:
                df_h = st.session_state.df.copy()
                # Sécurité conversion date
                df_h["date"] = pd.to_datetime(df_h["date"], dayfirst=True, errors='coerce')
                if "année" not in df_h.columns:
                    df_h["année"] = df_h["date"].dt.year
                
                # On s'assure que les années sont bien des entiers uniques
                df_h["année"] = pd.to_numeric(df_h["année"], errors='coerce')
                annees_brutes = df_h['année'].dropna().unique()
                liste_annees = sorted([int(a) for a in annees_brutes], reverse=True)

            @st.fragment
            def afficher_dashboard():
                # --- 1. CONFIGURATION DE BASE ---
                noms_mois_list = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", 
                                "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
                
                cols_filtres = st.columns([4, 2, 9, 1], gap="small")
                options_profil = ["Tous"] + st.session_state.groupes_liste
                # 1. On prépare la liste des profils réels
                groupes_reels = st.session_state.groupes_liste

                # 2. Logique conditionnelle pour "Tout le monde"
                if len(groupes_reels) > 1:
                    # S'il y a plus d'un profil, on propose le choix global
                    options_profil = ["Tous"] + groupes_reels
                else:
                    # S'il n'y a qu'un seul profil (ou zéro), on ne montre que celui-là
                    options_profil = groupes_reels if groupes_reels else ["Tous"]

                with cols_filtres[0]:
                    choix_actuel = st.pills(
                        "🎯 Profil", 
                        options_profil, 
                        selection_mode="single", # Pour garder le comportement selectbox
                        default=options_profil[st.session_state.filtre_profil_index],
                        key="choix_g_widget",
                        
                    )
                    # Sécurité : si rien n'est sélectionné, on garde l'ancien choix
                    if not choix_actuel: 
                        choix_actuel = options_profil[st.session_state.filtre_profil_index]
                    
                    st.session_state.filtre_profil_index = options_profil.index(choix_actuel)
                    

                if choix_actuel != "Tous":
                    profil_recherche = str(choix_actuel).strip().lower()
                    
                    # 1. On identifie les comptes rattachés au profil choisi
                    cps = [
                        c for c, cfg in st.session_state.config_groupes.items() 
                        if str(cfg.get("Groupe", "")).strip().lower() == profil_recherche
                    ]
                    
                    # 2. On calcule l'objectif du profil
                    obj = sum([v.get("Objectif", 0.0) for _, v in st.session_state.config_groupes.items() 
                            if str(v.get("Groupe", "")).strip().lower() == profil_recherche])
                    
                    # 3. On FILTRE le DataFrame pour ce profil uniquement
                    if not st.session_state.df.empty:
                        df_h = st.session_state.df.copy()
                        # Normalisation pour le filtrage
                        cps_norm = [str(c).strip().upper() for c in cps]
                        df_h["temp_compte"] = df_h["compte"].astype(str).str.strip().str.upper()
                        df_h = df_h[df_h["temp_compte"].isin(cps_norm)].copy()
                        df_h = df_h.drop(columns=["temp_compte"])
                    else:
                        df_h = st.session_state.df.copy()

                else:
                    # --- CAS Tous ---
                    # On garde TOUT le DataFrame sans aucun filtrage de compte
                    obj = sum([v.get("Objectif", 0.0) for v in st.session_state.config_groupes.values()])
                    
                    # --- CAS Tous ---
                    cps = list(st.session_state.config_groupes.keys())
                    # FORCE l'utilisation du DF original sans aucune transformation préalable
                    df_h = st.session_state.df.copy() 
                    
                    # On force la config de départ en MAJUSCULES
                    soldes_depart = {str(k).upper(): v.get("Solde", 0.0) for k, v in st.session_state.config_groupes.items()}
                    
                    # On recalcule TOUT à partir de zéro
                    soldes_finaux = calculer_evolution_comptes(df_h, soldes_depart, noms_mois_list)



                # --- 4. HARMONISATION ET SÉLECTEUR D'ANNÉE ---
                if not df_h.empty:
                    col_trouvee = next((c for c in df_h.columns if c.lower() in ['categorie', 'catégorie']), None)
                    if col_trouvee:
                        df_h = df_h.rename(columns={col_trouvee: 'categorie'})
                
                # On définit les années AVANT de calculer les soldes de départ
                annees_profil = sorted([int(a) for a in df_h['année'].dropna().unique()], reverse=True) if not df_h.empty else [pd.Timestamp.now().year]
                
                with cols_filtres[1]:
                    # On utilise segmented_control pour un look "onglet"
                    annee_choisie = st.pills(
                        "📅 Année", 
                        options=annees_profil,
                        default=annees_profil[0] if annees_profil else None,
                        key="annee_widget"
                    )
                    # Sécurité si l'utilisateur désélectionne tout
                    if not annee_choisie:
                        annee_choisie = annees_profil[0]


                # --- 4. CALCUL DES SOLDES AU 1ER JANVIER (L'étape qui manquait) ---
                soldes_depart = {}
                for c in cps:
                    nom_c = str(c).strip()
                    s_init = st.session_state.config_groupes.get(nom_c, {}).get("Solde", 0.0)
                    # Mouvements cumulés AVANT l'année choisie
                    mouv_prec = st.session_state.df[
                        (st.session_state.df['compte'].astype(str).str.upper() == nom_c.upper()) & 
                        (st.session_state.df['année'] < annee_choisie)
                    ]['montant'].sum()
                    soldes_depart[nom_c] = s_init + mouv_prec


                # --- 6. CALCULS NEON (Virements simulés & Historique) ---
                # --- CALCULS NEON (Virements simulés & Historique) ---
                soldes_finaux_bruts = calculer_evolution_comptes(df_h, soldes_depart, noms_mois_list)
                soldes_finaux = {compte: historique[-1] for compte, historique in soldes_finaux_bruts.items()}
                solde_global = sum(soldes_finaux.values())

                # --- 7. PRÉPARATION DES DONNÉES DE L'ANNÉE ---
                df_dash = df_h[df_h["année"] == annee_choisie].copy()

                # Initialisation par défaut pour éviter les NameError
                categories_dispo = []
                virements_techniques = []

                if not df_dash.empty:
                    # On récupère toutes les catégories présentes
                    categories_detectees = df_dash['categorie'].unique().tolist()
                    
                    # On identifie les virements (🔄, VERS, etc.)
                    virements_techniques = [
                        c for c in categories_detectees 
                        if any(x in str(c).upper() for x in ["🔄", "VERS ", "INTERNE"])
                    ]
                    
                    # On crée la liste des catégories "réelles" pour tes filtres
                    categories_dispo = sorted([
                        c for c in categories_detectees 
                        if c not in virements_techniques
                    ])

                # Sélecteur de mois (maintenant sécurisé)
                liste_m = sorted(df_dash['mois'].unique(), key=lambda x: noms_mois_list.index(x) if x in noms_mois_list else 0) if not df_dash.empty else []

                with cols_filtres[2]:
                    mois_choisi = st.pills(
                        "📆 Mois", 
                        options=liste_m,
                        default=liste_m[0] if liste_m else None,
                        key="mois_widget"
                    )
                    # Sécurité
                    if not mois_choisi and liste_m:
                        mois_choisi = liste_m[0]

                # --- 8. CONSTRUCTION DU TABLEAU DE DONNÉES (df_tab) ---
                # On utilise les résultats de la fonction NEON pour garantir la cohérence
                df_tab = pd.DataFrame({'mois': noms_mois_list})
                
                # Intégration de l'évolution de chaque compte
                for nom_c_upper, liste_valeurs in soldes_finaux_bruts.items():
                    # Retrouver le nom exact pour les colonnes
                    nom_original = next((c for c in cps if c.upper() == nom_c_upper), nom_c_upper)
                    df_tab[nom_original] = liste_valeurs

                # Calcul Revenus / Dépenses (sans virements)
                df_flux_annuel = df_dash[~df_dash["categorie"].isin(virements_techniques)].copy()
                if not df_flux_annuel.empty:
                    df_ann = df_flux_annuel.groupby('mois').agg(
                        Revenus=('montant', lambda x: x[x > 0].sum()),
                        Dépenses=('montant', lambda x: abs(x[x < 0].sum()))
                    ).reset_index()
                    df_tab = pd.merge(df_tab, df_ann, on='mois', how='left').fillna(0)
                else:
                    df_tab['Revenus'] = 0.0
                    df_tab['Dépenses'] = 0.0

                df_tab['Épargne'] = df_tab['Revenus'] - df_tab['Dépenses']
                df_tab['Patrimoine'] = df_tab[cps].sum(axis=1)

                # --- LA SUITE DE TON CODE (Affichage des Cartes, Jauge et Graphiques) ---
                # Utilise maintenant df_tab pour tes graphiques et solde_global pour tes KPI.

                st.write(f"#### 🏦 Situation Financière : {choix_actuel}")

                
                col_Card = "#3498db"
                cols_kpi = st.columns(len(cps) + 1)

                
                
                # --- 1. CARTE SOLDE GLOBAL ---
                with cols_kpi[0]:
                    st.markdown(f"""
                        <div style="background-color: {col_patri}; padding: 15px; border-radius: 12px; text-align: center; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);">
                            <p style="margin: 0; font-size: 12px; color: white; font-weight: bold; text-transform: uppercase;">💰 Solde Global</p>
                            <p style="margin: 0; font-size: 20px; color: white; font-weight: 800;">{solde_global:,.2f} €</p>
                        </div>
                    """, unsafe_allow_html=True)

                # --- 2. CARTES DES COMPTES INDIVIDUELS ---
                for i, c in enumerate(cps):
                    nom_propre = str(c).strip()
                    # On récupère la valeur avec une gestion de la casse pour éviter les ratés
                    val = soldes_finaux.get(nom_propre, soldes_finaux.get(nom_propre.upper(), 0.0))
                    
                    couleur_compte = st.session_state.config_groupes.get(nom_propre, {}).get("Couleur", "#3498db")

                    with cols_kpi[i+1]:
                        st.markdown(f"""
                            <div style="background-color: {couleur_compte}; padding: 15px; border-radius: 12px; text-align: center; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);">
                                <p style="margin: 0; font-size: 11px; color: white; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-transform: uppercase;">{nom_propre}</p>
                                <p style="margin: 0; font-size: 18px; color: white; font-weight: 700;">{val:,.2f} €</p>
                            </div>
                        """, unsafe_allow_html=True)

                c_recap, c_ann, c_graph = st.columns([1, 1, 1])

                with c_recap:
                    st.markdown(f"### 📋 Détails {mois_choisi} {annee_choisie}")
                    
                    # PRÉPARER LES DONNÉES DU mois
                    df_m = df_dash[(df_dash['mois'] == mois_choisi) & (df_dash['année'] == annee_choisie)].sort_values("date", ascending=False)
                    
                    is_vir = df_m['categorie'].str.upper().isin([c.upper() for c in virements_techniques])
                    df_virs = df_m[is_vir]
                    df_dep = df_m[(df_m['montant'] < 0) & (~is_vir)]
                    df_rev = df_m[(df_m['montant'] > 0) & (~is_vir)]

                    t_dep, t_rev, t_vir, t_graph = st.tabs([
                        f"Dépenses ({len(df_dep)})", 
                        f"Revenus ({len(df_rev)})", 
                        f"Transferts({len(df_virs)})",
                        "Analyses"
                    ])

                    with t_dep:
                        with st.container(height=430):
                            for _, row in df_dep.iterrows(): afficher_ligne_compacte(row, "#ff4b4b", "-")
                    
                    with t_rev:
                        with st.container(height=430):
                            for _, row in df_rev.iterrows(): afficher_ligne_compacte(row, "#00c853", "+")
                    
                    with t_vir:
                        with st.container(height=430):
                            for _, row in df_virs.iterrows(): afficher_ligne_compacte(row, "#9b59b6", "")

                    with t_graph:

                        categories_a_masquer = st.multiselect(
                        "Catégories à masquer", 
                        options=categories_dispo, 
                        key="mask_recap_unique" # Nouvelle clé unique pour éviter les conflits passés
                        )

                        # Utilisation de la liste d'exclusion définie plus haut
                        liste_exclusion = virements_techniques + categories_a_masquer
                        df_b = df_m[(df_m['montant'] < 0) & (~df_m['categorie'].isin(liste_exclusion))]
                        
                        if not df_b.empty:
                            df_res = df_b.groupby("categorie")["montant"].sum().abs().reset_index().sort_values("montant")
                            fig_b = px.bar(df_res, x="montant", y="categorie", orientation='h')
                            
                            max_val = df_res["montant"].max()
                            fig_b.update_traces(
                                marker_color=col_perf_dep, 
                                texttemplate='%{x:.0f} €',
                                textposition='outside', 
                                textfont=dict(size=10, color="gray")
                            )
                            fig_b.update_layout(
                                height=400, 
                                margin=dict(l=0, r=50, t=10, b=0), 
                                xaxis=dict(showgrid=False, visible=False, range=[0, max_val * 1.3]),
                                yaxis=dict(showgrid=False, tickfont=dict(color="gray")),
                                paper_bgcolor='rgba(0,0,0,0)',
                                plot_bgcolor='rgba(0,0,0,0)'
                            )
                            st.plotly_chart(fig_b, width='stretch', config={'displayModeBar': False})
                        else:
                            st.info("ℹ️ Aucune dépense à analyser pour ce mois.")
                            # Optionnel : afficher un graphique vide pour garder la structure
                            st.plotly_chart(go.Figure().update_layout(height=400, paper_bgcolor='rgba(0,0,0,0)'), width='stretch')





                    with c_ann:
                        st.subheader(f"🗓️ Récapitulatif Annuel {annee_choisie}")
                        
                        # --- 1. CRÉATION DES ONGLETS POUR NE RIEN PERDRE ---
                        # Tab 1 : Ton tableau actuel / Tab 2 : Le nouveau tableau par catégorie
                        tab_recap, tab_details_cat = st.tabs(["Flux & Patrimoine", "Détails par Catégorie"])

                        with tab_recap:
                            # --- TON CODE MODIFIÉ ---
                            df_template = pd.DataFrame({'mois': nomS_mois})
                            if not df_dash.empty:
                                # CORRECTION : On crée un DataFrame sans les virements internes pour le calcul
                                df_flux_reels = df_dash[~df_dash["categorie"].isin(virements_techniques)].copy()

                                # 1. On crée le récap sur les flux réels uniquement
                                df_reel_mois = df_flux_reels.groupby('mois')['montant'].agg(
                                    Revenus=lambda x: x[x > 0].sum(),
                                    Dépenses=lambda x: abs(x[x < 0].sum())
                                ).reset_index()

                                # 2. CRÉATION DE LA STRUCTURE COMPLÈTE (Jan à Déc)
                                df_tab = pd.merge(df_template, df_reel_mois, on='mois', how='left').fillna(0)

                                # 3. On calcule l'épargne mensuelle
                                df_tab['Épargne'] = df_tab['Revenus'] - df_tab['Dépenses']
                                
                                # 4. Tri chronologique
                                df_tab['mois_idx'] = df_tab['mois'].apply(lambda x: nomS_mois.index(x))
                                df_tab = df_tab.sort_values('mois_idx')

                                # 5. Calcul du Patrimoine cumulé
                                # Note : Le patrimoine doit inclure les virements (car l'argent bouge mais ne sort pas)
                                # Mais ici on le base sur l'épargne (Revenus - Dépenses sans virements), ce qui est mathématiquement identique
                                solde_depart_annee = sum(st.session_state.config_groupes[c].get("Solde", 0.0) for c in cps)
                                df_tab['Patrimoine'] = solde_depart_annee + df_tab['Épargne'].cumsum()

                                # --- AFFICHAGE DU TABLEAU ORIGINAL ---
                                h1, h2, h3, h4, h5 = st.columns([1.2, 1, 1, 1.2, 1.3])
                                base_h = "margin:0; font-weight:bold; font-size:10px; color:gray;"
                                
                                h1.markdown(f"<p style='{base_h} text-align:Center;'>mois</p>", unsafe_allow_html=True)
                                h2.markdown(f"<p style='{base_h} text-align:Center;'>REVENUS</p>", unsafe_allow_html=True)
                                h3.markdown(f"<p style='{base_h} text-align:Center;'>DÉPENSES</p>", unsafe_allow_html=True)
                                h4.markdown(f"<p style='{base_h} text-align:Center;'>ÉPARGNE</p>", unsafe_allow_html=True)
                                h5.markdown(f"<p style='{base_h} text-align:Center;'>SOLDE</p>", unsafe_allow_html=True)

                                st.markdown("<div style='margin-top: -10px;'></div>", unsafe_allow_html=True)
                                
                                with st.container(height=400):
                                    for _, row in df_tab.iterrows():
                                        c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1, 1.2, 1.3])
                                        color_ep = col_epargne if row['Épargne'] >= 0 else "#ff4b4b"
                                        base_d = "margin:0; font-weight:bold; font-size:13px;"
                                        opacity = "1.0" if (row['Revenus'] > 0 or row['Dépenses'] > 0) else "0.4"
                                        
                                        c1.markdown(f"<p style='{base_d} text-align:left; opacity:{opacity};'>{row['mois']}</p>", unsafe_allow_html=True)
                                        c2.markdown(f"<p style='{base_d} text-align:right; color:{col_rev}; opacity:{opacity};'>{row['Revenus']:,.2f}€</p>", unsafe_allow_html=True)
                                        c3.markdown(f"<p style='{base_d} text-align:right; color:{col_perf_dep}; opacity:{opacity};'>{row['Dépenses']:,.2f}€</p>", unsafe_allow_html=True)
                                        c4.markdown(f"<p style='{base_d} text-align:right; color:{color_ep}; opacity:{opacity};'>{row['Épargne']:,.2f}€</p>", unsafe_allow_html=True)
                                        c5.markdown(f"<p style='{base_d} text-align:right; color:{col_patri};'>{row['Patrimoine']:,.2f}€</p>", unsafe_allow_html=True)
                                        st.markdown("<hr style='margin: 4px 0; border: 0.1px solid #f8f9fb;'>", unsafe_allow_html=True)
                            else:
                                st.info("Aucune donnée disponible.")

                            with tab_details_cat:
                                
                                if not df_dash.empty:
                                    # 1. Préparation des données
                                    df_dep = df_dash[df_dash['montant'] < 0].copy()
                                    df_dep['montant'] = df_dep['montant'].abs()

                                    # 2. Création du Pivot avec TOUS les mois
                                    pivot_cat = df_dep.pivot_table(
                                        index='categorie', 
                                        columns='mois', 
                                        values='montant', 
                                        aggfunc='sum'
                                    ).fillna(0)

                                    for m in nomS_mois:
                                        if m not in pivot_cat.columns:
                                            pivot_cat[m] = 0.0
                                    
                                    pivot_cat = pivot_cat[nomS_mois]
                                    pivot_cat['Total'] = pivot_cat.sum(axis=1)

                                    # --- CSS AJUSTÉ POUR LE SYMBOLE € ---
                                    # On réduit un peu la taille (9.5px) pour compenser l'ajout du symbole
                                    style_texte = "margin:0; font-weight:bold; font-size:9.5px; white-space: nowrap; overflow: hidden;"
                                    
                                    # --- EN-TÊTES ---
                                    cols = st.columns([3] + [0.8] * 12 + [1.3]) # On élargit un peu le total final
                                    
                                    cols[0].markdown(f"<p style='{style_texte} text-align:left; color:gray;'>CATÉGORIE</p>", unsafe_allow_html=True)
                                    for i, mois in enumerate(nomS_mois):
                                        cols[i+1].markdown(f"<p style='{style_texte} text-align:center; color:gray;'>{mois[:3].upper()}</p>", unsafe_allow_html=True)
                                    cols[-1].markdown(f"<p style='{style_texte} text-align:right; color:gray;'>TOTAL</p>", unsafe_allow_html=True)

                                    st.markdown("<div style='margin-top: -5px;'></div>", unsafe_allow_html=True)

                                    with st.container(height=400):
                                        for cat, row in pivot_cat.iterrows():
                                            c = st.columns([3] + [0.8] * 12 + [1.3])
                                            
                                            # 1. nom de la catégorie
                                            nom_cat = cat[:14] + ".." if len(cat) > 14 else cat
                                            c[0].markdown(f"<p style='{style_texte} text-align:left;' title='{cat}'>{nom_cat}</p>", unsafe_allow_html=True)
                                            
                                            # 2. Valeurs par mois avec le symbole €
                                            for i, mois in enumerate(nomS_mois):
                                                val = row[mois]
                                                opacity = "1.0" if val > 0 else "0.15"
                                                color = col_perf_dep if val > 0 else "gray"
                                                # Affichage compact : 125€ au lieu de 125.00 €
                                                c[i+1].markdown(f"<p style='{style_texte} text-align:center; color:{color}; opacity:{opacity};'>{val:,.0f}€</p>", unsafe_allow_html=True)
                                            
                                            # 3. Total de la ligne
                                            c[-1].markdown(f"<p style='{style_texte} text-align:right; color:#e74c3c;'>{row['Total']:,.0f}€</p>", unsafe_allow_html=True)
                                            
                                            st.markdown("<hr style='margin: 2px 0; border: 0.1px solid #f8f9fb;'>", unsafe_allow_html=True)
                                else:
                                    st.info("Aucune donnée disponible.")
                    
                
                    with c_graph:
                        
        
                        st.subheader("📊 Graphiques et Budgets")
                        tab_graph, tab_budgets, tab_projet = st.tabs(["Graphiques", "Budgets","Projets"])
                        with tab_graph:
                            noms_mois = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", 
                                        "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

                            # 1. Préparation des soldes au 1er janvier
                            soldes_au_1er_janvier = {}
                            for c in cps:
                                nom_c = str(c).strip()
                                s_init = st.session_state.config_groupes.get(nom_c, {}).get("Solde", 0.0)
                                mouv_prec = st.session_state.df[
                                    (st.session_state.df['compte'].str.upper() == nom_c.upper()) & 
                                    (st.session_state.df['année'] < annee_choisie)
                                ]['montant'].sum()
                                soldes_au_1er_janvier[nom_c] = s_init + mouv_prec

                            # 2. Calcul des flux (Revenus / Dépenses)
                            df_flux_reels = df_dash[~df_dash["categorie"].str.contains("🔄", na=False)].copy()
                            if not df_flux_reels.empty:
                                df_ann = df_flux_reels.groupby('mois').agg(
                                    Revenus=('montant', lambda x: x[x > 0].sum()),
                                    Dépenses=('montant', lambda x: abs(x[x < 0].sum()))
                                ).reset_index()
                            else:
                                df_ann = pd.DataFrame(columns=['mois', 'Revenus', 'Dépenses'])

                            # 3. Calcul de l'évolution des comptes (Logic Neon)
                            historique_comptes = calculer_evolution_comptes(df_dash, soldes_au_1er_janvier, noms_mois)

                            # 4. Construction du DataFrame principal
                            df_tab = pd.DataFrame({'mois': noms_mois})
                            
                            # Intégration de l'évolution des comptes
                            for nom_c_upper, liste_valeurs in historique_comptes.items():
                                nom_original = next((c for c in cps if c.upper() == nom_c_upper), nom_c_upper)
                                df_tab[nom_original] = liste_valeurs

                            # Fusion des flux (Revenus/Dépenses)
                            df_tab = pd.merge(df_tab, df_ann, on='mois', how='left').fillna(0)
                            
                            # Sécurité : Si Revenus ou Dépenses manquent (ex: année vide), on les crée
                            for col in ['Revenus', 'Dépenses']:
                                if col not in df_tab.columns:
                                    df_tab[col] = 0.0

                            df_tab['Épargne'] = df_tab['Revenus'] - df_tab['Dépenses']
                            df_tab['Patrimoine'] = df_tab[cps].sum(axis=1)

                            # 5. Limite d'affichage
                            mois_avec_data = df_dash['mois'].unique()
                            max_idx = max([noms_mois.index(m) for m in mois_avec_data if m in noms_mois]) if len(mois_avec_data) > 0 else 0
                            df_tab_trace = df_tab.iloc[:max_idx + 1].copy()

                            # --- 6. AFFICHAGE JAUGE ---
                            solde_depart_total = sum(soldes_au_1er_janvier.values())
                            solde_actuel = df_tab_trace['Patrimoine'].iloc[-1] if not df_tab_trace.empty else solde_depart_total
                            
                            if obj > 0:
                                epargne_realisee = solde_actuel - solde_depart_total
                                prog = min(max(epargne_realisee / obj, 0.0), 1.0)
        
                                
                                # Affichage
                                c_t1, c_t2 = st.columns([1.5, 1.5])
                                c_t1.markdown(f"**Progression Épargne**")
                                
                                # On affiche : "Déjà épargné / Objectif"
                                c_t2.markdown(
                                    f"<p style='text-align:right; margin:0; font-size:12px;'>"
                                    f"<b>{epargne_realisee:,.0f}€</b> / {obj:,.0f}€ ({prog:.1%})</p>", 
                                    unsafe_allow_html=True
                                )
                                
                                # Couleur : Orange si peu avancé, Vert si objectif atteint
                                couleur_barre = col_jauge if prog < 1.0 else "#27ae60"

                                # TON BLOC HTML avec le nom variable corrigé
                                st.markdown(f"""
                                    <div style="background:#e0e0e0; border-radius:5px; height:12px; margin-bottom:5px; width:100%;">
                                        <div style="background:{couleur_barre}; width:{prog*100}%; height:12px; border-radius:5px;"></div>
                                    </div>
                                    <p style='font-size:10px; color:gray; margin:0;'>Cible de fin d'année : {(solde_depart_total + obj):,.0f}€</p>
                                """, unsafe_allow_html=True)
            
                                # On complète df_tab avec les colonnes de chaque compte pour le graphique d'évolution
                            

                        # --- 2. Flux Mensuels (Avec Dégradé Vertical) ---
                            # --- Préparation des données pour éviter la chute à 0 ---
                            df_plot = df_tab_trace.copy()
                            for col in ["Revenus", "Dépenses", "Épargne"]:
                                # Ici la colonne existe forcément grâce à la boucle de sécurité au point 4
                                df_plot[col] = df_plot[col].replace(0, None)

                            fig_p = go.Figure()

                                    # Fonction interne pour générer le dégradé à la volée pour chaque trace
                            def appliquer_gradient(couleur_hex):
                                        hex_c = couleur_hex.lstrip('#')
                                        r, g, b = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4))
                                        return dict(
                                            type='vertical',
                                            colorscale=[
                                                (0, f'rgba({r},{g},{b},0)'),   # 0% en bas
                                                (1, f'rgba({r},{g},{b},0.6)') # 60% en haut
                                            ]
                                        )

                            # Ajout des Revenus
                            fig_p.add_trace(go.Scatter(
                                x=df_plot["mois"], 
                                y=df_plot["Revenus"], 
                                name="Rev.", 
                                fill='tozeroy', 
                                line=dict(color=col_rev, width=2),
                                fillgradient=appliquer_gradient(col_rev),
                                connectgaps=False  # Empêche de relier les points si un mois est manquant
                            ))

                            # Ajout des Dépenses
                            fig_p.add_trace(go.Scatter(
                                x=df_plot["mois"], 
                                y=df_plot["Dépenses"], 
                                name="Dép.", 
                                fill='tozeroy', 
                                line=dict(color=col_perf_dep, width=2),
                                fillgradient=appliquer_gradient(col_perf_dep),
                                connectgaps=False
                            ))

                            # Ajout de l'Épargne
                            fig_p.add_trace(go.Scatter(
                                x=df_plot["mois"], 
                                y=df_plot["Épargne"], 
                                name="Épar.", 
                                fill='tozeroy', 
                                line=dict(color=col_epargne, width=2),
                                fillgradient=appliquer_gradient(col_epargne),
                                connectgaps=False
                            ))
                            fig_p.update_layout(
                                title=dict(text=f"Flux {annee_choisie} : {choix_actuel}", font=dict(size=14, color="white")),
                                height=180, 
                                margin=dict(l=0, r=0, t=40, b=0),
                                hovermode="x unified",
                                showlegend=True,
                                paper_bgcolor='rgba(0,0,0,0)', 
                                plot_bgcolor='rgba(0,0,0,0)',
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10, color="gray")),
                                
                                # --- LA CORRECTION EST ICI ---
                                xaxis=dict(
                                    showgrid=False, 
                                    tickfont=dict(size=10, color="gray"),
                                    type='category',             # On force le type catégorie
                                    categoryorder='array',       # On définit l'ordre manuellement
                                    categoryarray=noms_mois,     # On utilise ta liste ["Janvier", "Février", ...]
                                    range=[-0.2, 11.2]           # On force l'affichage de l'index 0 à 11
                                ),
                                # ----------------------------
                                
                                yaxis=dict(showgrid=False, visible=False)
                            )

                            st.plotly_chart(fig_p, width='content', config={'displayModeBar': False},key=f"flux_{choix_actuel}_{annee_choisie}")
                                    


                                                # --- PRÉPARATION DES DONNÉES PAR compte ---
                            for c in cps:
                                    nom_c = str(c).strip()
                                    df_mouv = df_dash[df_dash['compte'] == nom_c].groupby('mois')['montant'].sum().reset_index()
                                    df_mouv.columns = ['mois', 'Mouv_mois']
                                    df_tab = pd.merge(df_tab, df_mouv, on='mois', how='left').fillna(0)
                                    
                                    solde_initial_historique = st.session_state.config_groupes.get(nom_c, {}).get("Solde", 0.0)
                                    mouvements_passes = st.session_state.df[
                                        (st.session_state.df['compte'] == nom_c) & 
                                        (st.session_state.df['année'] < annee_choisie)
                                    ]['montant'].sum()
                                    
                                    solde_au_depart = solde_initial_historique + mouvements_passes
                                    df_tab[nom_c] = solde_au_depart + df_tab['Mouv_mois'].cumsum()
                                    df_tab = df_tab.drop(columns=['Mouv_mois'])


                                
                            fig_e = go.Figure()

                            # --- MODIFICATION ICI : On utilise directement la session chargée depuis GSheets ---
                            config_master = st.session_state.get('config_groupes', {})

                            for c in cps:
                                nom_c = str(c).strip()
                                if nom_c in df_tab.columns:
                                    # On récupère la couleur depuis notre config GSheets (bleu par défaut)
                                    couleur_hex = config_master.get(nom_c, {}).get("Couleur", "#1f77b4")
                                    
                                    # Sécurité anti-valeur vide
                                    if not isinstance(couleur_hex, str) or pd.isna(couleur_hex) or not couleur_hex.startswith("#"):
                                        couleur_hex = "#1f77b4"

                                    # Conversion HEX vers RGB pour le dégradé
                                    hex_c = couleur_hex.lstrip('#')
                                    r, g, b = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4))
                                    
                                    # On définit la couleur de départ (60% opacité) et de fin (0% opacité)
                                    c_start = f'rgba({r}, {g}, {b}, 0.6)'
                                    c_stop = f'rgba({r}, {g}, {b}, 0.0)'

                                    fig_e.add_trace(go.Scatter(
                                    x=df_tab_trace["mois"], 
                                    y=df_tab_trace[nom_c], 
                                    name=nom_c, 
                                    # --- ON SUPPRIME stackgroup='one' ---
                                    mode='lines', # On force le mode ligne
                                    fill='tozeroy', # Garde le remplissage vers le bas
                                    line=dict(color=couleur_hex, width=2),
                                    # On utilise une couleur de remplissage très transparente 
                                    # pour voir les courbes derrière
                                    fillgradient=dict(
                                        type='vertical',
                                        colorscale=[(0, c_stop), (1, c_start)]),
                                    hoverinfo='x+y+name'
                                ))

                            # Ligne de total
                            fig_e.add_trace(go.Scatter(
                                x=df_tab_trace["mois"], y=df_tab_trace["Patrimoine"], 
                                name="TOTAL", line=dict(color=col_patri, width=3, dash='dot')
                            ))

                            # --- CONFIGURATION DE L'AXE X POUR VOIR TOUTE L'ANNÉE ---
                            fig_e.update_layout(
                                # ... tes autres réglages (height, margin, etc.) ...
                                xaxis=dict(
                                    showgrid=False, 
                                    tickfont=dict(color="gray"),
                                    # Force l'affichage de Janvier à Décembre
                                    type='category',
                                    categoryorder='array',
                                    categoryarray=nomS_mois,
                                    range=[-0.2, 11.2] # Un peu de marge pour ne pas coller aux bords
                                ),
                                yaxis=dict(showgrid=False, visible=False),
                                hovermode="x unified"
                            )

                            fig_e.update_layout(
                                    title=dict(text=f"Évolution comptes {annee_choisie} : {choix_actuel}", font=dict(size=14, color="white")),
                                    height=300, 
                                    margin=dict(l=0, r=0, t=40, b=0),
                                    hovermode="x unified",
                                    showlegend=True,
                                    xaxis=dict(showgrid=False, tickfont=dict(color="gray")),
                                    yaxis=dict(showgrid=False, visible=False),
                                    paper_bgcolor='rgba(0,0,0,0)',
                                    plot_bgcolor='rgba(0,0,0,0)',
                                    legend=dict(orientation="h", yanchor="bottom", y=0.93, xanchor="right", x=1, font=dict(color="gray", size=10))
                                )

                            st.plotly_chart(fig_e, width='content', config={'displayModeBar': False},key=f"patri_{choix_actuel}_{annee_choisie}")

                        with tab_budgets:  
                            # --- LOGIQUE DASHBOARD BUDGET PAR PROFIL ---
                            user = st.session_state["username"]
                            
                            # On utilise les variables déjà définies en haut de ta page
                            # choix_actuel (le profil), cps (la liste des comptes du groupe), mois_choisi
                            
                            # 1. Préparation du calcul des dépenses réelles
                            stats_depenses = {}
                            depenses_groupe = pd.DataFrame()

                            if not df_dash.empty:
                                # On filtre df_dash (qui est déjà filtré par année et groupe) pour n'avoir que le mois choisi
                                df_mois = df_dash[df_dash['mois'] == mois_choisi].copy()
                                
                                # On ne garde que les dépenses (montant < 0)
                                depenses_groupe = df_mois[df_mois['montant'] < 0]
                                
                                if not depenses_groupe.empty:
                                    # On somme par catégorie
                                    stats_depenses = depenses_groupe.groupby('categorie')['montant'].sum().abs().to_dict()

                            # 2. Chargement et Agrégation des Budgets GSheets
                            # On doit récupérer les budgets de TOUS les comptes du groupe (cps)
                            budgets_cumules = {}
                            
                            try:
                                   
                                
                                # Requête SQL ciblée : on ne prend que l'user, le mois, les comptes du groupe (cps) et le type 'categorie'
                                query = text("""
                                    SELECT nom, somme 
                                    FROM budgets 
                                    WHERE utilisateur = :u 
                                    AND mois = :m 
                                    AND compte = ANY(:cps) 
                                    AND type = 'categorie'
                                """)
                                
                                with engine.connect() as conn_sql:
                                    # ANY(:cps) permet de passer une liste Python directement à SQL
                                    df_budget_groupe = pd.read_sql(query, conn_sql, params={
                                        "u": user, 
                                        "m": mois_choisi, 
                                        "cps": cps
                                    })
                                
                                if not df_budget_groupe.empty:
                                    # On cumule les sommes par catégorie (ex: si "🛒 Alimentation" existe sur CCP et Commun)
                                    budgets_cumules = df_budget_groupe.groupby('nom')['somme'].sum().to_dict()
                                    
                            except Exception as e:
                                st.error(f"Erreur lors de la lecture des budgets Neon : {e}")

                            # 3. Affichage des Jauges
                            if budgets_cumules:
                                st.subheader(f"🎯 Objectifs du profil : {choix_actuel} ({mois_choisi})")
                                
                                cols = st.columns(3)
                                # On boucle sur les catégories qui ont un budget défini
                                for i, (cat_nom, plafond) in enumerate(budgets_cumules.items()):
                                    # On récupère le réel
                                    reell = float(stats_depenses.get(cat_nom, 0.0))
                                    plafond = float(plafond)
                                    
                                    # Calcul Ratio & Couleurs
                                    ratio = min(reell / plafond, 1.0) if plafond > 0 else 0
                                    couleur = "#28a745" if ratio < 0.8 else "#ffc107" if ratio < 1.0 else "#dc3545"
                                    
                                    with cols[i % 3]:
                                        restant = plafond - reell
                                        st.metric(
                                            label=cat_nom, 
                                            value=f"{round(reell, 2)}€", 
                                            delta=f"{round(restant, 2)}€ restants",
                                            delta_color="normal" if restant >= 0 else "inverse"
                                        )
                                        
                                        # Barre de progression
                                        st.markdown(f"""
                                            <div style="background-color: #e9ecef; border-radius: 10px; height: 12px; width: 100%; margin-bottom: 20px;">
                                                <div style="background-color: {couleur}; width: {ratio*100}%; height: 100%; border-radius: 10px;"></div>
                                            </div>
                                        """, unsafe_allow_html=True)
                            else:
                                st.info(f"Aucun budget configuré pour le profil **{choix_actuel}** en **{mois_choisi}**.")

                        with tab_projet:
                            with st.container(height=430):
                                st.subheader(f"🚀 Gestion des Projets de {choix_actuel}")
                                user = st.session_state["username"]

                            # 1. CALCUL DE L'ÉPARGNE RÉELLE CUMULÉE (Flux uniquement, sans le solde initial)
                                if 'df_tab' in locals() and not df_tab.empty:
                                    # On fait la somme de tous les mois de la colonne 'Épargne' du tableau récap
                                    epargne_physique_cumulee = float(df_tab['Épargne'].sum())
                                else:
                                    # Calcul de secours si df_tab n'est pas dispo
                                    if not df_dash.empty:
                                        rev = df_dash[df_dash['montant'] > 0]['montant'].sum()
                                        dep = abs(df_dash[df_dash['montant'] < 0]['montant'].sum())
                                        epargne_physique_cumulee = rev - dep
                                    else:
                                        epargne_physique_cumulee = 0.0

                                # Le solde global pour la simulation (par défaut le patrimoine actuel)
                                solde_bancaire_actuel = epargne_physique_cumulee

                                # 2. LECTURE DES DONNÉES DEPUIS NEON
                                try:
                                       
                                    
                                    # On filtre par user et par Profil (le nom de ton groupe)
                                    query = text("""
                                        SELECT * FROM projets 
                                        WHERE utilisateur = :u AND profil = :p
                                    """)
                                    
                                    with engine.connect() as conn_sql:
                                        mes_projets_df = pd.read_sql(query, conn_sql, params={
                                            "u": user, 
                                            "p": choix_actuel
                                        })
                                    
                                    if not mes_projets_df.empty:
                                        # Harmonisation des colonnes (SQL renvoie souvent des minuscules)
                                        mes_projets_df.columns = [c.capitalize() if c.lower() != 'user' else c for c in mes_projets_df.columns]
                                        
                                        # Conversion propre
                                        mes_projets_df['Date'] = pd.to_datetime(mes_projets_df['Date'], errors='coerce')
                                        mes_projets_df['Cout'] = pd.to_numeric(mes_projets_df['Cout'], errors='coerce')
                                        
                                        if 'Capa' not in mes_projets_df.columns: 
                                            mes_projets_df['Capa'] = 0.0
                                        else:
                                            mes_projets_df['Capa'] = pd.to_numeric(mes_projets_df['Capa'], errors='coerce').fillna(0.0)
                                        
                                        mes_projets_df = mes_projets_df.sort_values('Date')
                                    else:
                                        mes_projets_df = pd.DataFrame(columns=['Date', 'Nom', 'Cout', 'Capa', 'profil'])

                                except Exception as e:
                                    st.error(f"Erreur lecture projets Neon : {e}")
                                    mes_projets_df = pd.DataFrame()

                                # 3. PARAMÈTRES
                                with st.container(border=True):
                                    epargne_depart_simu = st.number_input("💰 Solde de départ pour simulation (€)", value=solde_bancaire_actuel, key="input_simu_depart")
                                    st.caption(f"Épargne réelle cumulée : {epargne_physique_cumulee:,.2f}€")

                            # --- 4. NOUVEAU PROJET ---
                                st.markdown(f"➕ Nouveau projet")

                                # Création du formulaire (clear_on_submit=True videra les champs après l'enregistrement)
                                with st.form("form_nouveau_projet", clear_on_submit=True, border=True):
                                    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                                    
                                    with c1: 
                                        nom_p = st.text_input("Nom", key="new_proj_nom")
                                    with c2: 
                                        cout_p = st.number_input("Coût (€)", min_value=0.0, key="new_proj_cout")
                                    
                                    aujourdhui = date.today()
                                    with c3:
                                        date_p = st.date_input(
                                            "Échéance", 
                                            value=aujourdhui,
                                            min_value=aujourdhui,
                                            key="new_proj_date"
                                        )
                                    with c4: 
                                        capa_p = st.number_input("Épargne/m", min_value=0.0, key="new_proj_capa")
                                    
                                    # Le bouton DOIT être un form_submit_button pour fonctionner dans un formulaire
                                    submit_btn = st.form_submit_button("🚀 Enregistrer le projet", use_container_width=True, type="primary")

                                    if submit_btn:
                                        if nom_p:
                                            try:
                                                   
                                                
                                                query = text("""
                                                    INSERT INTO projets (utilisateur, profil, nom, cout, date, capa)
                                                    VALUES (:u, :p, :n, :c, :d, :ca)
                                                """)
                                                
                                                params = {
                                                    "u": str(user),
                                                    "p": str(choix_actuel),
                                                    "n": str(nom_p),
                                                    "c": float(cout_p),
                                                    "d": date_p,
                                                    "ca": float(capa_p)
                                                }
                                                
                                                with engine.begin() as conn_sql:
                                                    conn_sql.execute(query, params)
                                                
                                                # --- REFRESH ---
                                                st.cache_data.clear() 
                                                st.session_state["active_tab"] = "Projets"
                                                
                                                st.success(f"✅ Projet '{nom_p}' enregistré avec succès !")
                                                time.sleep(1)
                                                relancer_avec_succes()
                                                
                                            except Exception as e:
                                                st.error(f"Erreur lors de l'enregistrement Neon : {e}")
                                        else:
                                            st.warning("Donnez au moins un nom à votre projet !")

                                # --- 5. LISTE ET CALCULS ---
                                st.markdown(f"🚧 Mes projets")
                                if not mes_projets_df.empty:
                                    # Initialisation
                                    solde_cascade = float(epargne_depart_simu)
                                    cumul_epargne_reel_restant = float(epargne_physique_cumulee) 
                                    date_ref = datetime.now().date()

                                    for index, p in mes_projets_df.iterrows():
                                        if pd.isna(p['Date']): continue
                                        
                                        # 1. Variables de base
                                        d_p = p['Date'].date() if hasattr(p['Date'], 'date') else p['Date']
                                        nb_mois = max(0, (d_p.year - date_ref.year) * 12 + (d_p.month - date_ref.month))
                                        cout_projet = float(p['Cout'])
                                        capa_projet = float(p.get('Capa', 0.0))
                                        
                                        # 2. Calcul de la projection pour ce projet spécifique
                                        # Argent futur = ce qu'il reste des projets d'avant + épargne générée jusqu'à cette date
                                        argent_total_futur = solde_cascade + (capa_projet * nb_mois)
                                        
                                        # Ratios pour les barres de progression
                                        montant_reel_affiche = min(cumul_epargne_reel_restant, cout_projet)
                                        ratio_reel = (montant_reel_affiche / cout_projet) if cout_projet > 0 else 1.0
                                        
                                        montant_futur_affiche = min(argent_total_futur, cout_projet)
                                        ratio_futur = (montant_futur_affiche / cout_projet) if cout_projet > 0 else 1.0

                                        with st.container(border=True):
                                            col_txt, col_stat = st.columns([3, 1])
                                            with col_txt:
                                                st.write(f"### {p['Nom']}")
                                                st.caption(f"📅 {d_p.strftime('%d/%m/%Y')} | 📈 {capa_projet}€/mois")
                                                
                                                st.progress(ratio_reel, text=f"Épargne Réelle : {int(ratio_reel*100)}% ({montant_reel_affiche:,.2f}€ / {cout_projet:,.2f}€)")
                                                st.progress(ratio_futur, text=f"Projection : {int(ratio_futur*100)}% ({montant_futur_affiche:,.2f}€ / {cout_projet:,.2f}€)")

                                                # --- TA LOGIQUE D'AFFICHAGE DU SUCCÈS ---
                                                if argent_total_futur >= cout_projet:
                                                    st.success(f"✅ Faisable (Excédent : {argent_total_futur - cout_projet:,.2f}€)")
                                                    # MISE À JOUR : On retire le coût du projet du disponible pour le suivant
                                                    solde_cascade = argent_total_futur - cout_projet
                                                    cumul_epargne_reel_restant = max(0.0, cumul_epargne_reel_restant - cout_projet)
                                                else:
                                                    st.error(f"❌ Il manquera {cout_projet - argent_total_futur:,.2f}€ à l'échéance")
                                                    # MISE À JOUR : Plus rien ne reste pour les projets suivants
                                                    solde_cascade = 0
                                                    cumul_epargne_reel_restant = 0

                                                

                                            with col_stat:
                                                with st.popover("✏️"):
                                                    st.write(f"**Modifier {p['Nom']}**")
                                                    
                                                    # On encapsule les champs dans un formulaire dédié à ce projet précis
                                                    with st.form(key=f"form_edit_{index}"):
                                                        n_cout = st.number_input("Coût (€)", value=float(p['Cout']))
                                                        n_capa = st.number_input("Épargne / mois (€)", value=float(p.get('Capa', 0)))
                                                        n_date = st.date_input("Date échéance", value=p['Date'])
                                                        
                                                        # Le bouton de validation du formulaire
                                                        submit_edit = st.form_submit_button("Enregistrer les modifs", use_container_width=True, type="primary")
                                                        
                                                        if submit_edit:
                                                            try:
                                                                   
                                                                with engine.begin() as conn_sql:
                                                                    # UPDATE ciblé
                                                                    conn_sql.execute(text("""
                                                                        UPDATE projets 
                                                                        SET cout = :c, capa = :ca, date = :d 
                                                                        WHERE utilisateur = :u AND profil = :p AND nom = :n
                                                                    """), {
                                                                        "c": n_cout, "ca": n_capa, "d": n_date,
                                                                        "u": user, "p": choix_actuel, "n": p['Nom']
                                                                    })
                                                                
                                                                # --- REFRESH ---
                                                                st.cache_data.clear()
                                                                st.session_state["active_tab"] = "Projets"
                                                                
                                                                # Petit message éphémère avant le reload
                                                                st.toast(f"Projet '{p['Nom']}' mis à jour !", icon="✅")
                                                                time.sleep(0.5)
                                                                relancer_avec_succes()
                                                                
                                                            except Exception as e:
                                                                st.error(f"Erreur modif : {e}")

                                            

                                                # --- SUPPRESSION DU PROJET ---
                                                if st.button("🗑️", key=f"del_{index}"):
                                                    try:
                                                           
                                                        with engine.begin() as conn_sql:
                                                            # DELETE ciblé
                                                            conn_sql.execute(text("""
                                                                DELETE FROM projets 
                                                                WHERE utilisateur = :u AND profil = :p AND nom = :n
                                                            """), {
                                                                "u": user, "p": choix_actuel, "n": p['Nom']
                                                            })
                                                        
                                                        st.cache_data.clear()
                                                        st.session_state["active_tab"] = "Projets"
                                                        relancer_avec_succes()
                                                    except Exception as e:
                                                        st.error(f"Erreur suppression : {e}")
            afficher_dashboard()


                                
    

    elif selected == "Prévisionnel":


        # --- 1. INITIALISATION DES VARIABLES (Toujours en premier) ---
        if "selected_prevs" not in st.session_state:
            st.session_state.selected_prevs = set()
        # --- 1. INITIALISATION AVEC RECHARGEMENT FORCÉ ---
        # On charge si la variable n'existe pas OU si elle est vide
        if "df_prev" not in st.session_state or st.session_state.df_prev is None or st.session_state.df_prev.empty:
            st.session_state.df_prev = charger_previsions_neon()
        
        # Initialisation de l'état d'affichage par mois (True par défaut)
        if "show_prev_mois" not in st.session_state:
            st.session_state.show_prev_mois = {m: True for m in nomS_mois}

        # Initialisation des états pour la persistance
        if "p_choix_g" not in st.session_state: 
            st.session_state.p_choix_g = "Tous"

        if "p_choix_a" not in st.session_state: 
            st.session_state.p_choix_a = int(time.localtime().tm_year)

        if "p_choix_m" not in st.session_state: 
            # On s'assure que le mois par défaut est bien le mois actuel
            st.session_state.p_choix_m = nomS_mois[time.localtime().tm_mon - 1]

        # --- SÉCURITÉ ANTI-KEYERROR & MISE À JOUR DYNAMIQUE ---
        if "df_prev" in st.session_state and st.session_state.df_prev is not None:
            df_p = st.session_state.df_prev.copy()
            
            # 1. On s'assure que la colonne date est bien au format datetime
            if "date" in df_p.columns:
                df_p["date"] = pd.to_datetime(df_p["date"], errors='coerce')
                
                # 2. On RECALCULE toujours le mois et l'année à partir de la date réelle
                # C'est ça qui corrige ton bug !
                df_p["année"] = df_p["date"].dt.year
                df_p["mois"] = df_p["date"].dt.month.map(
                    lambda x: nomS_mois[int(x)-1] if pd.notnull(x) and 0 < x <= 12 else None
                )

            # On réinjecte le DataFrame "propre"
            st.session_state.df_prev = df_p

        @st.fragment
        def afficher_zone_previsionnelle():

            # --- 2. FILTRES COMPACTS ---
            cols_f = st.columns([4, 2, 9, 1], gap="small")
            
            # FILTRE PROFIL
            options_g = ["Tous"] + st.session_state.groupes_liste if len(st.session_state.groupes_liste) > 1 else st.session_state.groupes_liste
            idx_g = options_g.index(st.session_state.p_choix_g) if st.session_state.p_choix_g in options_g else 0

            groupes_reels = st.session_state.groupes_liste
            if len(groupes_reels) > 1:
                options_g = ["Tous"] + groupes_reels
            else:
                options_g = groupes_reels if groupes_reels else ["Tous"]
            
            with cols_f[0]:
                choix_g = st.pills("🎯 Profil", options_g, 
                           default=options_g[idx_g] if idx_g < len(options_g) else options_g[0], 
                           key="prev_g_widget")
                if choix_g: st.session_state.p_choix_g = choix_g

                
            
            # On cherche "groupe" ou "Groupe" sans se soucier de la casse
            # --- RÉCUPÉRATION DES COMPTES DU PROFIL ---
            if choix_g == "Tous":
                # On prend TOUTES les clés du dictionnaire de config
                cps = list(st.session_state.config_groupes.keys())
            else:
                # On filtre pour ne garder que ceux du groupe sélectionné
                cps = []
                for compte, config in st.session_state.config_groupes.items():
                    # Sécurité : si config est un dictionnaire
                    if isinstance(config, dict):
                        # On cherche 'groupe' ou 'Groupe'
                        groupe_du_compte = config.get("groupe", config.get("Groupe", ""))
                        
                        # Comparaison propre
                        if str(groupe_du_compte).strip().upper() == str(choix_g).strip().upper():
                            cps.append(compte)
                    else:
                        # Si jamais ta config n'est pas un dictionnaire mais une simple valeur
                        if str(config).strip().upper() == str(choix_g).strip().upper():
                            cps.append(compte)

            # --- DEBUG DE SÉCURITÉ ---
            if not cps:
                st.warning(f"⚠️ La liste de comptes (cps) est vide pour le choix : {choix_g}")
                # st.write("Contenu de config_groupes :", st.session_state.config_groupes) # À décommenter si besoin
            
            # 1. On récupère les années des transactions réelles
            annees_reelles = st.session_state.df['année'].dropna().unique().tolist()

            # 2. On récupère AUSSI les années des prévisions (si le DF n'est pas vide)
            annees_prev = []
            if not st.session_state.df_prev.empty:
                annees_prev = st.session_state.df_prev['année'].dropna().unique().tolist()

            # 3. On fusionne tout : Réels + Prévisions + Année en cours
            # Le set() permet d'éliminer les doublons automatiquement
            toutes_annees = set([int(a) for a in annees_reelles] + 
                                [int(a) for a in annees_prev] + 
                                [int(time.localtime().tm_year)])

            liste_a = sorted(list(toutes_annees), reverse=True)

            # 4. Gestion de l'index pour le widget
            idx_a = liste_a.index(st.session_state.p_choix_a) if st.session_state.p_choix_a in liste_a else 0

            with cols_f[1]:
                annee_p = st.pills("📅 Année", liste_a, 
                                default=liste_a[idx_a] if idx_a < len(liste_a) else liste_a[0], 
                                key="prev_a_widget"
                                )
                if not annee_p: annee_p = liste_a[idx_a]
                st.session_state.p_choix_a = annee_p

            # --- LOGIQUE DYNAMIQUE DES MOIS ---

            # 1. On récupère les mois où il y a des prévisions pour l'année sélectionnée
            mois_avec_donnees = []
            if not st.session_state.df_prev.empty:
                # On filtre par l'année choisie pour n'avoir que les mois pertinents
                mask_annee = st.session_state.df_prev["année"].astype(str) == str(annee_p)
                mois_avec_donnees = st.session_state.df_prev[mask_annee]["mois"].unique().tolist()

            # 2. On définit le mois actuel (pour pouvoir ajouter des prévisions sur le mois en cours)
            mois_actuel = nomS_mois[time.localtime().tm_mon - 1]

            # 3. On construit la liste : "Tous les mois" + les mois trouvés + le mois actuel (sans doublons)
            # On respecte l'ordre chronologique de nomS_mois
            mois_a_afficher = [m for m in nomS_mois if m in mois_avec_donnees or m == mois_actuel]
            liste_mois_select = ["Tous les mois"] + mois_a_afficher

            # 4. Calcul de l'index
            if st.session_state.p_choix_m in liste_mois_select:
                idx_m = liste_mois_select.index(st.session_state.p_choix_m)
            else:
                # Par défaut on se met sur le mois actuel s'il est dans la liste, sinon "Tous les mois"
                idx_m = liste_mois_select.index(mois_actuel) if mois_actuel in liste_mois_select else 0

            # --- AFFICHAGE DU FILTRE ---
            with cols_f[2]:
                mois_p = st.pills(
                    "📆 Mois", 
                    liste_mois_select, 
                    default=liste_mois_select[idx_m], 
                    key="prev_m_widget"
                    
                )
                
                if not mois_p:
                    mois_p = liste_mois_select[idx_m]
                    
                st.session_state.p_choix_m = mois_p

            # --- 3. CALCULS ---
            # (Tes calculs restent identiques jusqu'aux CARDS...)
            # Assure-toi que df_reel_filtre et df_prev_filtre sont bien calculés avec cps
            categories_detectees = st.session_state.df['categorie'].unique().tolist() if not st.session_state.df.empty else []
            virements_techniques = [c for c in categories_detectees if "🔄" in str(c) or "VERS " in str(c).upper() or "INTERNE" in str(c).upper()]
            
            mois_idx_fin = nomS_mois.index(mois_p) if mois_p != "Tous les mois" else 11
            annee_p_int = int(annee_p)

            # On harmonise cps et la colonne compte pour être sûr qu'ils se trouvent
            cps_upper = [str(c).strip().upper() for c in cps]

            df_reel_filtre = st.session_state.df.copy()
            df_reel_filtre = df_reel_filtre[df_reel_filtre["compte"].astype(str).str.strip().str.upper().isin(cps_upper)]

            df_prev_filtre = st.session_state.df_prev.copy()
            df_prev_filtre = df_prev_filtre[df_prev_filtre["compte"].astype(str).str.strip().str.upper().isin(cps_upper)]
            df_reel_filtre["date"] = pd.to_datetime(df_reel_filtre["date"], dayfirst=True, errors='coerce')

            soldes_finaux_comptes = {}
            for c in cps:
                nom_c_upper = str(c).strip().upper()
                # On va chercher le solde de départ dans la config
                # ATTENTION : la clé dans config_groupes est peut-être "CCP Theo" (pas en majuscule)
                solde_initial = float(st.session_state.config_groupes.get(c, {}).get("Solde", 0.0))
                soldes_finaux_comptes[nom_c_upper] = solde_initial

            # --- 1. TRAITEMENT DU RÉEL (CSV) ---
            # On définit les virements déjà présents pour éviter les doublons
            virements_reels = df_reel_filtre[df_reel_filtre['categorie'].str.contains("🔄", na=False)]

            for _, ligne in df_reel_filtre.iterrows():
                mnt = float(ligne['montant'])
                cpte_source = str(ligne['compte']).strip().upper()
                cat = str(ligne['categorie']).upper()

                # A. Impact direct (On touche au compte qui a la ligne)
                if cpte_source in soldes_finaux_comptes:
                    soldes_finaux_comptes[cpte_source] += mnt
                
                # B. Impact indirect (Contrepartie virtuelle)
                if "🔄" in cat:
                    # On cherche le nom exact dans la config pour trouver le groupe
                    nom_source_cfg = next((k for k in st.session_state.config_groupes.keys() if k.strip().upper() == cpte_source), None)
                    
                    if nom_source_cfg:
                        groupe_src = st.session_state.config_groupes[nom_source_cfg].get("Groupe")
                        
                        for nom_c, cfg in st.session_state.config_groupes.items():
                            nom_c_upper = str(nom_c).strip().upper()
                            
                            # Si même groupe, compte différent et le nom du compte est dans le libellé
                            if cfg.get("Groupe") == groupe_src and nom_c_upper != cpte_source:
                                mots = [m for m in nom_c_upper.split() if len(m) > 2]
                                if mots and mots[0] in cat:
                                    
                                    # ANTI-DOUBLON : Est-ce que la ligne d'arrivée existe déjà dans notre sélection ?
                                    deja_present = not virements_reels[
                                        (virements_reels['compte'].str.upper() == nom_c_upper) & 
                                        (abs(virements_reels['montant']) == abs(mnt))
                                    ].empty
                                    
                                    if not deja_present:
                                        # On ne voit pas la ligne, donc on l'ajoute au compte cible (même s'il n'est pas dans cps)
                                        if mnt < 0:
                                            soldes_finaux_comptes[nom_c_upper] = soldes_finaux_comptes.get(nom_c_upper, 0) + abs(mnt)
                                        else:
                                            soldes_finaux_comptes[nom_c_upper] = soldes_finaux_comptes.get(nom_c_upper, 0) - abs(mnt)
                                    break

            # --- 2. TRAITEMENT DU PRÉVISIONNEL ---
            # (On applique exactement la même logique sur df_p_periode)
            # ... (Tu peux copier la boucle ci-dessus en changeant df_reel_filtre par df_p_periode
                
            mask_p = (df_prev_filtre["année"] < annee_p_int) | \
                    ((df_prev_filtre["année"] == annee_p_int) & 
                    (df_prev_filtre["mois"].apply(lambda x: nomS_mois.index(x) <= mois_idx_fin if x in nomS_mois else False)))
            
            df_p_periode = df_prev_filtre[mask_p]

            for _, ligne in df_p_periode.iterrows():
                if st.session_state.show_prev_mois.get(ligne['mois'], True):
                    mnt = float(ligne['montant'])
                    cpte_source = str(ligne['compte']).strip().upper()
                    cat = str(ligne['categorie']).upper()

                    if cpte_source in soldes_finaux_comptes:
                        soldes_finaux_comptes[cpte_source] += mnt
                    
                    if "🔄" in cat or "VERS" in cat or "INTERNE" in cat:
                        for nom_c_cible in soldes_finaux_comptes.keys():
                            if nom_c_cible != cpte_source and any(m in cat for m in nom_c_cible.split() if len(m) > 2):
                                if mnt < 0:
                                    soldes_finaux_comptes[nom_c_cible] += abs(mnt)
                                else:
                                    soldes_finaux_comptes[nom_c_cible] -= abs(mnt)
                                break

            # C. Patrimoine Global et Solde Départ Graphique
            patrimoine_global_projete = sum(soldes_finaux_comptes.values())
            # C'est ici qu'on harmonise : le graphique démarre sur la valeur calculée
            solde_base_annee = patrimoine_global_projete 

            # D. Préparation affichage
            df_combi = pd.concat([
                df_reel_filtre[df_reel_filtre["année"] == annee_p_int],
                df_prev_filtre[df_prev_filtre["année"] == annee_p_int]
            ], ignore_index=True)
            
            df_tab_data = df_combi.copy()
            # Suppression des prévisions si l'oeil est fermé
            for m, visible in st.session_state.show_prev_mois.items():
                if not visible:
                    idx_a_supprimer = df_tab_data[(df_tab_data["mois"] == m) & (df_tab_data["nom"].str.contains(r"\[PRÉVI\]", na=False))].index
                    df_tab_data = df_tab_data.drop(idx_a_supprimer)

            stats = df_tab_data.groupby('mois')['montant'].agg(
                Rev=lambda x: x[x>0].sum(), 
                Dep=lambda x: abs(x[x<0].sum())
            ).reset_index()


            # --- 4. CARDS ---
            st.markdown(f"#### 🏦 Situation Financière prévisionnelle : {choix_g}")
            cols_kpi = st.columns(len(cps) + 1)
            with cols_kpi[0]:
                st.markdown(f'<div style="background-color:{col_patri}; padding:15px; border-radius:12px; text-align:center; color:white;"><p style="margin:0; font-size:12px;font-weight: bold ;opacity:0.8;">GLOBAL PROJETÉ</p><p style="margin:0; font-size:20px; font-weight:800;">{patrimoine_global_projete:,.2f} €</p></div>', unsafe_allow_html=True)
            for i, c in enumerate(cps):
                couleur = st.session_state.config_groupes.get(c, {}).get("Couleur", "#3498db")
                with cols_kpi[i+1]:
                # Version avec sécurité anti-crash
                    solde_affiche = soldes_finaux_comptes.get(str(c).strip().upper(), 0.0)

                    st.markdown(f'<div style="background-color:{couleur}; padding:15px; border-radius:12px; text-align:center; color:white;"><p style="margin:0; font-size:11px;font-weight: bold; text-transform:uppercase;">{c}</p><p style="margin:0; font-size:18px; font-weight:700;">{solde_affiche:,.2f} €</p></div>', unsafe_allow_html=True)

            st.write("")

            # --- 5. DISPOSITION 3 COLONNES ---
            col1, col2, col3 = st.columns([1.5, 1.2, 2.3])

            if "nb_lignes_saisie" not in st.session_state:
                st.session_state.nb_lignes_saisie = 1

            @st.fragment
            def fragment_formulaire_previsions(cats, cps, annee_p_int, mois_idx_fin):
                st.markdown("##### ➕ Ajouter Prévisions")
                
                # 1. On définit la liste des catégories
                # On mélange ta liste fixe (complète) avec les catégories uniques du DF pour ne rien louper
                if not st.session_state.df.empty:
                    cats_du_df = st.session_state.df['categorie'].unique().tolist()
                    # On fusionne avec ta liste globale et on enlève les doublons avec set()
                    cats = sorted(list(set(LISTE_categorieS_COMPLETE + cats_du_df)))
                else:
                    cats = sorted(LISTE_categorieS_COMPLETE)
                if "lignes_indices" not in st.session_state:
                    st.session_state.lignes_indices = [0]

                # 2. LE FORMULAIRE (Contient uniquement les champs et le bouton de validation final)
                with st.form("bulk_add_form_v4"):
                    nouvelles_previs = []

                    with st.container(height=385, border=False):
                        for idx in st.session_state.lignes_indices:
                            with st.container():
                                                        # À l'intérieur de ta boucle for idx...
                                c1, c2, c_eur = st.columns([2, 0.8, 0.2]) # On ajoute la colonne pour l'Euro
                                nom = c1.text_input("libellé", key=f"n_{idx}", label_visibility="collapsed", placeholder="nom...")
                                mnt = c2.number_input("montant", key=f"m_{idx}", label_visibility="collapsed", step=10.0, format="%.2f")
                                c_eur.markdown("<p style='margin-top:7px; font-weight:bold; color:gray;'>€</p>", unsafe_allow_html=True)
                                
                                c_cat, c_cpte, c_date = st.columns([1, 1, 1])
                                cat = c_cat.selectbox("Cat", cats, key=f"cat_{idx}", label_visibility="collapsed")
                                cpte = c_cpte.selectbox("compte", cps, key=f"cp_{idx}", label_visibility="collapsed")
                                def_date = pd.Timestamp(year=annee_p_int, month=mois_idx_fin + 1 if mois_idx_fin < 11 else 1, day=1)
                                dte = c_date.date_input("date", value=def_date, key=f"d_{idx}", label_visibility="collapsed")
                                
                                nouvelles_previs.append({"date": dte, "nom": nom, "montant": mnt, "categorie": cat, "compte": cpte})
                                st.markdown("<hr style='margin:10px 0; opacity:0.1;'>", unsafe_allow_html=True)

                        # SEUL ce bouton est autorisé dans le formulaire
                    submit = st.form_submit_button("Enregistrer les prévisions 💾", width='stretch', type="primary")

                # --- 3. LES BOUTONS DE GESTION (HORS DU FORMULAIRE) ---
                # Ces boutons sont maintenant APRES le bloc "with st.form"
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])

                if col_btn1.button("➕ Ligne", use_container_width=True):
                    prochain_idx = max(st.session_state.lignes_indices) + 1 if st.session_state.lignes_indices else 0
                    st.session_state.lignes_indices.append(prochain_idx)
                    st.rerun(scope="fragment") # Ne relance QUE le fragment

                if col_btn2.button("🗑️ Ligne", use_container_width=True):
                    if len(st.session_state.lignes_indices) > 1:
                        st.session_state.lignes_indices.pop()
                        st.rerun(scope="fragment")

                if col_btn3.button("🔄 Reset", use_container_width=True):
                    st.session_state.lignes_indices = [0]
                    st.rerun(scope="fragment")

                # 4. Logique de sauvegarde (S'exécute quand submit est True)
                if submit:
                    lignes_a_sauver = [l for l in nouvelles_previs if l["nom"].strip() != ""]
                    if lignes_a_sauver:
                        df_new = pd.DataFrame(lignes_a_sauver)
                        df_new["date"] = pd.to_datetime(df_new["date"])
                        df_new["nom"] = "[PRÉVI] " + df_new["nom"]
                        df_new["mois"] = df_new["date"].dt.month.apply(lambda x: nomS_mois[x-1])
                        df_new["année"] = df_new["date"].dt.year
                        
                        st.session_state.df_prev = pd.concat([st.session_state.df_prev, df_new], ignore_index=True)
                        sauvegarder_previsions_neon(st.session_state.df_prev, st.session_state["user"])
                        
                        st.session_state.lignes_indices = [0]
                        st.success("Enregistré !")
                        relancer_avec_succes()
            
            with col1:
                # Préparation des catégories avant l'appel
                if not st.session_state.df.empty:
                    cats_du_df = st.session_state.df['categorie'].unique().tolist()
                    cats = sorted(list(set(LISTE_categorieS_COMPLETE + cats_du_df)))
                else:
                    cats = sorted(LISTE_categorieS_COMPLETE)
                    
                # Appel de la fonction fragment
                fragment_formulaire_previsions(cats, cps, annee_p_int, mois_idx_fin)


            with col2:


                @st.dialog("Confirmer la suppression")
                def confirmer_suppression_dialog():
                    nb = len(st.session_state.selected_prevs)
                    st.write(f"⚠️ Êtes-vous sûr de vouloir supprimer les **{nb}** prévisions sélectionnées ?")
                    st.write("Cette action est irréversible.")
                    
                    col_yes, col_no = st.columns(2)
                    
                    if col_yes.button("🔥 Oui, supprimer tout", type="primary", use_container_width=True):
                        # Logique de suppression
                        indices_existants = [i for i in st.session_state.selected_prevs if i in st.session_state.df_prev.index]
                        st.session_state.df_prev = st.session_state.df_prev.drop(indices_existants)
                        
                        # Sauvegarde Cloud
                        sauvegarder_previsions_neon(st.session_state.df_prev, st.session_state["user"])
                        
                        # Reset et fermeture
                        st.session_state.selected_prevs = set()
                        st.success("Supprimé avec succès !")
                        st.rerun() # Relance pour mettre à jour les graphiques et fermer le dialog

                    if col_no.button("Annuler", use_container_width=True):
                        st.rerun() # Ferme simplement la boîte de dialogue


                st.markdown(f"##### 📋 Prévisions {mois_p} {annee_p}")


                # --- 1. PRÉPARATION DES DONNÉES ---
                df_source = st.session_state.df_prev.copy()

                # --- 2. FILTRAGE ---
                if mois_p == "Tous les mois":
                    # On filtre quand même par ANNÉE pour ne pas voir tout l'historique prévisionnel
                    df_mois_prev = df_source[df_source["année"].astype(str) == str(annee_p)]
                else:
                    # Filtrage par MOIS ET ANNÉE
                    df_mois_prev = df_source[
                        (df_source["mois"].astype(str).str.strip().str.capitalize() == mois_p.strip().capitalize()) &
                        (df_source["année"].astype(str) == str(annee_p))
                    ]

                # --- 3. TRI ET AFFICHAGE ---
                if not df_mois_prev.empty:
                    df_mois_prev = df_mois_prev.sort_values("date")
                else:
                    st.info(f"Aucune donnée trouvée pour {mois_p} {annee_p}")
                    

                if not df_mois_prev.empty:
                    # --- 1. FONCTIONS DE SYNCHRONISATION (Callbacks) ---
                    def sync_individual_check(idx):
                        """S'exécute à chaque clic sur une checkbox individuelle"""
                        # La clé du widget est mise à jour avant l'appel du callback
                        if st.session_state[f"p_check_{idx}"]:
                            st.session_state.selected_prevs.add(idx)
                        else:
                            st.session_state.selected_prevs.discard(idx)
                        
                        # On recalcule immédiatement si tout est sélectionné pour la Master Checkbox
                        all_indices = set(df_mois_prev.index)
                        st.session_state.master_check = all_indices.issubset(st.session_state.selected_prevs)

                        
                    def toggle_all():
                        """S'exécute UNIQUEMENT quand on clique sur la Master Checkbox"""
                        # On utilise directement l'état du widget 'master_check'

                        # 1. Vérification de sécurité pour éviter le crash
                        if "selected_prevs" not in st.session_state:
                            st.session_state.selected_prevs = set()
                            
                        if st.session_state.get("master_check", False):
                            for idx in df_mois_prev.index:
                                st.session_state.selected_prevs.add(idx)
                                st.session_state[f"p_check_{idx}"] = True
                        else:
                            for idx in df_mois_prev.index:
                                st.session_state.selected_prevs.discard(idx)
                                st.session_state[f"p_check_{idx}"] = False

                    # --- 2. CALCUL ET MISE À JOUR DE L'ÉTAT (Le secret est là) ---
                    all_indices = set(df_mois_prev.index)
                    # On vérifie si tout est réellement sélectionné dans le set
                    is_all_selected = all_indices.issubset(st.session_state.selected_prevs) if all_indices else False
                    
                    # On force la valeur de la Master Checkbox dans le session_state
                    # Cela permet de la décocher visuellement si un élément en bas est décoché
                    st.session_state.master_check = is_all_selected

                    # --- 3. BARRE D'ACTIONS ---
                    c_master, c_del = st.columns([1, 1])

                    with c_master:
                        # IMPORTANT : On ne met plus 'value='. 
                        # Streamlit va lire st.session_state.master_check automatiquement.
                        st.checkbox(
                            "Tout sélectionner", 
                            key="master_check", 
                            on_change=toggle_all
                        )

                  
                    
                    # On désactive le bouton s'il n'y a rien à supprimer
                    if c_del.button("Supprimer", type="primary", use_container_width=True):
                        confirmer_suppression_dialog()

                    @st.dialog("Modifier la prévision")
                    def modifier_prevision_dialog(row, idx):
                        st.write(f"Modification de : **{row['nom']}**")
                        
                        # --- RÉCUPÉRATION DES CATÉGORIES ---
                        # On prend toutes les catégories uniques de ton DataFrame principal
                        # Si df_f ou st.session_state.df n'existe pas, on met une liste par défaut
                        if 'df' in st.session_state:
                            list_cats = sorted(st.session_state.df['categorie'].unique().tolist())
                        else:
                            list_cats = [row['categorie']] # Au moins la catégorie actuelle
                        
                        # Formulaire
                        new_nom = st.text_input("Nom", value=row['nom'])
                        new_mnt = st.number_input("Montant", value=float(row['montant']), step=10.0)
                        
                        # Utilisation de la liste dynamique
                        index_cat = list_cats.index(row['categorie']) if row['categorie'] in list_cats else 0
                        new_cat = st.selectbox("Catégorie", options=list_cats, index=index_cat)
                        
                        new_date = st.date_input("Date", value=row['date'])

                        if st.button("Enregistrer les modifications", type="primary"):
                            try:
                                # 1. On met à jour la ligne DIRECTEMENT dans le DataFrame local (session_state)
                                # On utilise .at[idx, ...] pour cibler précisément la bonne ligne
                                st.session_state.df_prev.at[idx, 'nom'] = new_nom
                                st.session_state.df_prev.at[idx, 'montant'] = new_mnt
                                st.session_state.df_prev.at[idx, 'categorie'] = new_cat
                                st.session_state.df_prev.at[idx, 'date'] = pd.to_datetime(new_date)

                                # 2. On appelle ta fonction de sauvegarde qui va :
                                #    - Supprimer tout l'ancien bloc de l'utilisateur sur Neon
                                #    - Réinsérer le DataFrame tout neuf (avec la modif)
                                succes = sauvegarder_previsions_neon(st.session_state.df_prev, st.session_state.user)

                                if succes:
                                    st.success("✅ Modification enregistrée dans Neon !")
                                    # 1. On efface la version en mémoire
                                    if "df_prev" in st.session_state:
                                        del st.session_state.df_prev
                                    
                                    # 2. On vide le cache Streamlit (si tu en utilises un)
                                    st.cache_data.clear()
                                    
                                    # 3. On relance l'app pour qu'elle réexécute charger_previsions_neon()
                                    st.rerun()
                                    
                            except Exception as e:
                                st.error(f"Erreur lors de la modification : {e}")


                    with st.container(height=470):
                        for idx, r in df_mois_prev.iterrows():
                            # On ajoute une colonne 'c_edit' à la fin
                            c_check, c_info, c_mnt, c_edit = st.columns([0.4, 3.0, 1, 1])

                            # 1. Checkbox (ton code existant)
                            sel = c_check.checkbox("", key=f"p_check_{idx}", label_visibility="collapsed", 
                                                on_change=sync_individual_check, args=(idx,))
                            
                            if sel: st.session_state.selected_prevs.add(idx)
                            else: st.session_state.selected_prevs.discard(idx)

                            # 2. Infos (ton code existant)
                            date_str = r['date'].strftime('%d/%m') if pd.notnull(r['date']) else "??/??"
                            nom_propre = r['nom'].replace('[PRÉVI] ','')
                            c_info.markdown(f"""
                                <div style='line-height:1.2;'>
                                    <b style='font-size:13px;'>{nom_propre}</b><br>
                                    <small style='color:gray;'>{date_str} • {r['compte']} • {r['categorie']}</small>
                                </div>
                            """, unsafe_allow_html=True)

                            # 3. Montant (ton code existant)
                            color = col_rev if r['montant'] > 0 else col_perf_dep
                            c_mnt.markdown(f"<p style='color:{color}; font-weight:bold; text-align:right; margin-top:5px; font-size:14px;'>{r['montant']:.0f}€</p>", unsafe_allow_html=True)

                            # 4. LE NOUVEAU BOUTON MODIFIER
                            if c_edit.button("✏️", key=f"edit_{idx}", help="Modifier cette prévision",use_container_width=True):
                                modifier_prevision_dialog(r, idx)

                            st.markdown("<hr style='margin:4px 0; opacity:0.1;'>", unsafe_allow_html=True)
                

        # Calcul du point de départ au 1er janvier de l'année sélectionnée pour TOUS les comptes du profil
            # 1. Somme des soldes initiaux saisis en config
            base_config = 0.0
            for c in cps:
                base_config += float(st.session_state.config_groupes.get(c, {}).get("Solde", 0.0))

            # 2. Somme de tout le REEL (CSV) avant l'année en cours
            base_reel_passe = st.session_state.df[
                (st.session_state.df["compte"].isin(cps)) & 
                (st.session_state.df["année"] < annee_p_int)
            ]["montant"].sum()

        

            # 3. Somme de toutes les PREVISIONS avant l'année en cours
            base_prev_passee = st.session_state.df_prev[
                (st.session_state.df_prev["compte"].isin(cps)) & 
                (st.session_state.df_prev["année"] < annee_p_int)
            ]["montant"].sum()

            solde_base_annee = base_config + base_reel_passe + base_prev_passee

            with col3: 
                st.markdown("📊 Récap des prévisions annuel")
                        # MODIFICATION ICI : Utiliser df_tab_data au lieu de df_combi
                df_tab_p = pd.DataFrame({'mois': nomS_mois})
                mask_interne = df_tab_data['categorie'].str.upper().str.contains("🔄|VERS|INTERNE", na=False)

                stats = df_tab_data[~mask_interne].groupby('mois')['montant'].agg(
                    Rev=lambda x: x[x>0].sum(), 
                    Dep=lambda x: abs(x[x<0].sum())
                ).reset_index()

                df_tab_p = pd.merge(df_tab_p, stats, on='mois', how='left').fillna(0)
                df_tab_p['Epargne'] = df_tab_p['Rev'] - df_tab_p['Dep']
                df_tab_p['Solde'] = solde_base_annee + df_tab_p['Epargne'].cumsum()

                def get_gradient(hex_color):
                    hex_c = hex_color.lstrip('#')
                    r, g, b = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4))
                    return dict(type='vertical', colorscale=[(0, f'rgba({r},{g},{b},0)'), (1, f'rgba({r},{g},{b},0.6)')])

                fig_p = go.Figure()
                fig_p.add_trace(go.Scatter(
                    x=df_tab_p["mois"], y=df_tab_p["Solde"],
                    fill='tozeroy', line=dict(color=col_patri, width=3),
                    fillgradient=get_gradient(col_patri), name="Solde"
                ))
                fig_p.update_layout(
                    height=104, margin=dict(l=0,r=0,t=10,b=10),
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    xaxis=dict(showgrid=False, tickfont=dict(size=10, color="gray")),
                    yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.1)', visible=False)
                )
                st.plotly_chart(fig_p, width='stretch', config={'displayModeBar': False})

                            

                                        # CSS pour supprimer les marges inutiles des colonnes Streamlit dans le tableau
                
                            # 4. AFFICHAGE DU TABLEAU
                st.markdown(f"""<div style="display:flex; font-size:9px; color:gray; font-weight:bold; padding:5px 10px;">
                                <span style="width:5px;"></span>
                                <span style="width:100px;">ACTIVER PREVISIONS</span>
                                <span style="flex:1;text-align:left;">MOIS</span>
                                <span style="flex:1;text-align:center;">REVENUS</span>
                                <span style="flex:1;text-align:center;">DÉPENSES</span>
                                <span style="flex:1;text-align:center;">ÉPARGNE</span>
                                <span style="flex:1.2;text-align:center;">SOLDE</span></div>""", unsafe_allow_html=True)
                

                
                with st.container(height=390):
                    for _, row in df_tab_p.iterrows():
                        m = row['mois']
                        is_visible = st.session_state.show_prev_mois.get(m, True)
                        bg = "rgba(243, 156, 18, 0.12)" if m == mois_p else "transparent"
                        color_ep = col_epargne if row['Epargne'] >= 0 else "#ff4b4b"
                        opacity = "1" if is_visible else "0.5"

                        # Ligne Streamlit : Colonne Bouton + Colonne Texte HTML
                        c_eye, c_text = st.columns([0.1, 0.9])
                        
                        with c_eye:
                            # Choix de l'icône Bootstrap
                            icon_class = "bi-eye" if is_visible else "bi-eye-slash"
                            icon_color = col_patri if is_visible else "#5E4D4C"
                            
                            # On crée un bouton transparent avec l'icône à l'intérieur
                            # Le bouton Streamlit déclenche toujours l'action, le HTML gère le look
                            if st.button(" ", key=f"btn_{m}", help=f"Afficher/Masquer {m}",width='stretch'):
                                st.session_state.show_prev_mois[m] = not is_visible
                                st.rerun(scope="fragment")
                        


                        st.markdown("""
                        <style>
                            /* 1. Style pour les boutons de gestion (Larges) */
                            .stButton > button {
                                width: 100% !important; /* Force le bouton à prendre toute la colonne */
                                height: 45px !important;
                                border-radius: 10px !important;
                                font-weight: bold !important;
                            }

                            /* 2. Style spécifique pour l'OEIL uniquement */
                            /* On cible le bouton par son aide (help) ou sa position */
                            button[help*="Afficher/Masquer"] {
                                width: 3.5rem !important;
                                height: 3.5rem !important;
                                border-radius: 50% !important; /* Rend l'oeil rond */
                                border: none !important;
                                background: transparent !important;
                            }
                        </style>
                        """, unsafe_allow_html=True)
                        # On superpose l'icône visuelle par-dessus le bouton (CSS Hack pour l'esthétique)
                        st.markdown(f"""
                            <i class="bi {icon_class}" style="
                                position: absolute; 
                                margin-top: -4.2rem; 
                                margin-left: 3vh; 
                                font-size: 1.3rem; 
                                color: {icon_color}; 
                                pointer-events: none;
                            "></i>
                        """, unsafe_allow_html=True)
                        

                        with c_text:
                            st.markdown(f"""
                            <div style="display:flex; padding:6px 10px; background:{bg}; opacity:{opacity}; border-radius:4px; margin-bottom:2px; font-size:11px; border-bottom:1px solid rgba(128,128,128,0.05);">
                                <span style="width:60px; font-weight:bold; color:#7f8c8d;">{m}</span>
                                <span style="flex:1; text-align:right; color:{col_rev};">{row['Rev']:,.2f}</span>
                                <span style="flex:1; text-align:right; color:{col_perf_dep};">{row['Dep']:,.2f}</span>
                                <span style="flex:1; text-align:right; color:{color_ep}; font-weight:bold;">{row['Epargne']:,.2f}</span>
                                <span style="flex:1.2; text-align:right; color:{col_patri}; font-weight:bold;">{row['Solde']:,.2f}€</span>
                            </div>""", unsafe_allow_html=True)
        afficher_zone_previsionnelle()
                
    elif selected == "comptes":
            st.markdown("""
                <div style="background-color: rgba(255, 255, 255, 0.05); padding: 20px; border-radius: 15px; border: 1px solid rgba(128, 128, 128, 0.1); margin-bottom: 20px;">
                    <h2 style="margin: 0; font-size: 24px;">👥 Structure & comptes</h2>
                    <p style="color: gray; font-size: 14px;">Organisez vos finances par groupes et configurez vos soldes de départ.</p>
                </div>
            """, unsafe_allow_html=True)

            # --- SECTION 1 : ARCHITECTURE (groupeS & compteS REGROUPÉS) ---
            col_side1, col_config, col_notes, col_side2 = st.columns([1.5, 1, 1, 1.5])

            # --- POPOVER 1 : CONFIGURATION ---
            with col_config:
                with st.popover("⚙️ Ajouter des comptes bancaires/profils", width='stretch'):
                    tab_comptes, tab_groupes = st.tabs(["💳 comptes","📁 profils"])

           # --- POPOVER BLOC-NOTES ---
            with col_notes:
                with st.popover("📝 Notes", width='stretch'):
                    st.subheader("Mon Bloc-notes")
                    
                    # Le text_area affiche la note actuelle
                    note_text = st.text_area(
                        "Notes libres :", 
                        value=st.session_state.bloc_notes_content,
                        placeholder="Noter un virement à faire, un objectif...",
                        height=250,
                        key="note_area_input"
                    )
                    
                    # Bouton pour enregistrer réellement dans le Google Sheet
                    if st.button("💾 Enregistrer la note", width='stretch'):
                        st.session_state.bloc_notes_content = note_text
                        sauvegarder_notes_neon(note_text, st.session_state.user)
                        st.toast("Notes sauvegardées!")

                    # --- ONGLET 1 : GESTION DES GROUPES ---
                    with tab_groupes:
                        st.caption("Les profils permettent de segmenter votre patrimoine (ex: Commun, Théo, Aude, Entreprise ,...).")
                        
                        # Ajouter
                        n_g = st.text_input("nom du nouveau profil", placeholder="Ex: votre Prénom", key="add_grp_input_unique")
                        
                        if st.button("➕ Ajouter le profil", width='stretch'):
                            if n_g and n_g not in st.session_state.groupes_liste:
                                st.session_state.groupes_liste.append(n_g)
                                # On stocke le message dans le session_state
                                st.session_state.msg_info = f"✅ Profil '{n_g}' créé ! 💡 Note : Ce profil n'est pas encore sauvegardé dans la base. Pour le conserver, vous devez maintenant l'assigner à au moins un compte."
                                st.rerun()

                        # Affichage du message persistant (à placer juste au dessus ou en dessous du bouton)
                        if "msg_info" in st.session_state:
                            st.info(st.session_state.msg_info)
                            # Optionnel : bouton pour fermer le message
                            if st.button("Masquer le message"):
                                del st.session_state.msg_info
                                st.rerun()
                        
                        st.divider()
                        
                        # Supprimer (Ici, il est conseillé de garder la sauvegarde pour que la suppression soit réelle)
                        if st.session_state.groupes_liste:
                            g_del = st.selectbox("Profil à supprimer", st.session_state.groupes_liste, key="sel_del_grp")
                            if st.button("🗑️ Supprimer le profil", width='stretch', type="secondary"):
                                if len(st.session_state.groupes_liste) > 1:
                                    st.session_state.groupes_liste.remove(g_del)
                                    # On sauvegarde la suppression pour éviter qu'il ne réapparaisse au prochain refresh
                                    sauvegarder_config_neon(st.session_state.groupes_liste, st.session_state["user"])
                                    st.warning(f"groupe '{g_del}' supprimé")
                                    relancer_avec_succes()
                        else:
                            st.write("Aucun profil à supprimer.")

                    # --- ONGLET 2 : AJOUTER/SUPPRIMER DES compteS ---
                    with tab_comptes:
                        st.caption("Gérez les comptes qui n'ont pas d'import CSV (Manuels).")
                        
                        # Ajouter
                        n_compte_nom = st.text_input("nom du compte à créer", placeholder="Ex: Livret A, CCP,...", key="input_new_cpte_unique")
                        if st.button("➕ Créer le compte", width='stretch'):
                            if n_compte_nom:
                                if n_compte_nom not in st.session_state.config_groupes:
                                    # On assigne le premier groupe par défaut
                                    groupe_defaut = st.session_state.groupes_liste[0] if st.session_state.groupes_liste else "Général"
                                    st.session_state.config_groupes[n_compte_nom] = {"groupe": groupe_defaut, "Objectif": 0.0, "Solde": 0.0}
                                    sauvegarder_config_neon(st.session_state.config_groupes, st.session_state["user"])
                                    st.toast(f"compte '{n_compte_nom}' créé !")
                                    relancer_avec_succes()
                        
                        st.divider()

                        # 1. On récupère la liste des comptes
                        comptes_existants = list(st.session_state.config_groupes.keys())

                        # 2. Le Selectbox (on utilise une clé unique)
                        cpte_a_suppr = st.selectbox(
                            "compte à supprimer", 
                            [""] + comptes_existants, 
                            key="selectbox_suppression_compte"
                        )

                        # 3. Le Bouton
                        if st.button("🗑️ Supprimer le compte", use_container_width=True, type="secondary"):
                            if cpte_a_suppr:
                                try:
                                    with engine.begin() as conn:
                                        # 1. On nettoie les tables où le compte apparaît
                                        # On utilise le nom du compte (cpte_a_suppr) et l'utilisateur
                                        tables_a_nettoyer = ["budgets", "previsions", "transactions","configuration"]
                                        
                                        for table in tables_a_nettoyer:
                                            conn.execute(
                                                text(f'DELETE FROM {table} WHERE compte = :c AND utilisateur = :u'),
                                                {"c": cpte_a_suppr, "u": st.session_state["user"]}
                                            )
                                        
                                        # 2. Cas particulier de la table 'configuration'
                                        # Si c'est une table avec une colonne JSON, on met à jour le dictionnaire
                                        if cpte_a_suppr in st.session_state.config_groupes:
                                            del st.session_state.config_groupes[cpte_a_suppr]
                                        
                                        # 3. On sauvegarde la nouvelle configuration (sans le compte)
                                        sauvegarder_config_neon(st.session_state.config_groupes, st.session_state["user"])
                                        
                                    # ... fin de ton bloc try ...
                                    st.cache_data.clear()
                                    st.toast(f"✅ Compte '{cpte_a_suppr}' supprimé", icon="🗑️")
                                    time.sleep(1) # Petit délai pour laisser lire le message
                                    st.rerun()
                                    
                                except Exception as e:
                                    st.error(f"Erreur lors de la suppression globale : {e}")

                st.markdown("<br>", unsafe_allow_html=True)

            # --- SECTION 2 : CONFIGURATION GÉNÉRALE (LA GRILLE) ---
            col_config, col_calc = st.columns([1.2, 0.8], gap="large")


            with col_config:
                st.markdown("### ⚙️ Configuration des soldes et objectifs")
                
                comptes_csv = df_h["compte"].unique().tolist() if not df_h.empty else []
                comptes_config = list(st.session_state.config_groupes.keys())
                tous_les_comptes = sorted(list(set(comptes_csv + comptes_config)))

                if not tous_les_comptes:
                    st.info("Démarrer par importer un fichier ou créer un compte manuel.")
                else:
                    # En-têtes de colonnes propres
                    h1, h2, h3, h4 = st.columns([2, 2, 1.5, 1.5])
                    h1.caption("NOM DU COMPTE")
                    h2.caption("PROFIL ASSIGNÉ")
                    h3.caption("SOLDE INITIAL")
                    h4.caption("OBJECTIF")

                    with st.form("form_objectifs_final", border=False):
                        for cpte in tous_les_comptes:
                            # Style de la ligne
                            with st.container():
                                old_val = st.session_state.config_groupes.get(cpte, {"Groupe": st.session_state.groupes_liste[0], "Objectif": 0.0, "Solde": 0.0})
                                try:
                                    idx = st.session_state.groupes_liste.index(old_val.get("Groupe"))
                                except:
                                    idx = 0

                                c1, c2, c3, c4 = st.columns([2, 2, 1.5, 1.5])
                                
                                with c1:
                                    badge = "🔘" if cpte in comptes_csv else "⌨️"
                                    st.markdown(f"**{badge} {cpte}**")
                                
                                with c2:
                                    n_grp = st.selectbox(f"G_{cpte}", st.session_state.groupes_liste, index=idx, key=f"f_grp_{cpte}", label_visibility="collapsed")
                                
                                with c3:
                                    n_solde = st.number_input(f"S_{cpte}", value=float(old_val.get("Solde", 0.0)), key=f"f_solde_{cpte}", label_visibility="collapsed", step=100.0)
                                
                                with c4:
                                    n_obj = st.number_input(f"O_{cpte}", value=float(old_val.get("Objectif", 0.0)), key=f"f_obj_{cpte}", label_visibility="collapsed", step=100.0)
                                
                                # Mise à jour silencieuse dans le dictionnaire
                                st.session_state.config_groupes[cpte] = {"Groupe": n_grp, "Objectif": n_obj, "Solde": n_solde}
                                st.markdown('<hr style="margin: 5px 0; border:0; border-top:1px solid rgba(128,128,128,0.1);">', unsafe_allow_html=True)

                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.form_submit_button("💾 Enregistrer toutes les modifications", width='content', type="primary"):
                            sauvegarder_config_neon(st.session_state.config_groupes, st.session_state["user"])
                            st.success("Configuration sauvegardée avec succès !")
                            time.sleep(1)
                            relancer_avec_succes()
            # On définit le fragment
            @st.fragment
            def calculateur_prorata():
                st.markdown("### 🧮 Calculateur au Prorata")
                
                with st.container(border=True):
                    st.caption("Calculez la répartition équitable en temps réel.")
                    
                    # Entrées des revenus (Chaque modification ne recharge QUE ce bloc)
                    sal_perso = st.number_input("Mon salaire net (€)", value=0.0, step=50.0, key="calc_perso")
                    sal_copine = st.number_input("Salaire partenaire (€)", value=0.0, step=50.0, key="calc_copine")
                    objectif_commun = st.number_input("Objectif commun total (€)", value=0.0, step=50.0, key="calc_obj")
                    
                    # Calculs logiques (instantanés)
                    total_salaires = sal_perso + sal_copine
                    
                    if total_salaires > 0:
                        part_perso = (sal_perso / total_salaires)
                        part_copine = (sal_copine / total_salaires)
                        
                        contrib_perso = part_perso * objectif_commun
                        contrib_copine = part_copine * objectif_commun
                        
                        # Affichage des résultats
                        st.markdown("---")
                        st.markdown(f"**Répartition des parts :**")
                        
                        c_res1, c_res2 = st.columns(2)
                        with c_res1:
                            st.metric("Ma part", f"{contrib_perso:.0f} €", f"{part_perso*100:.1f}%")
                        with c_res2:
                            st.metric("Part partenaire", f"{contrib_copine:.0f} €", f"{part_copine*100:.1f}%")
                        
                        st.info(f"💡 Chacun contribue à hauteur de **{(objectif_commun/total_salaires)*100:.1f}%** de son revenu net.")
                    else:
                        st.warning("Veuillez saisir des revenus valides.")

            # On appelle la fonction dans ta colonne
            with col_calc:
                calculateur_prorata()
    

            
        
             
    elif selected == "Gérer":
            
            
        
                # --- 1. INITIALISATION DES ÉTATS (Toujours hors du if empty) ---
            for key, val in {
                'filter_g': "Tous", 'filter_c': "Tous", 
                'filter_a': "Toutes", 'filter_m': "Tous", 
                'input_new_cat': ""
            }.items():
                if key not in st.session_state: st.session_state[key] = val

            # --- 2. PRÉPARATION DES DONNÉES SÉCURISÉE ---
            # On crée un DataFrame vide avec les bonnes colonnes si df_h est vide
            if df_h.empty:
                df_edit = pd.DataFrame(columns=["date", "nom", "montant", "categorie", "compte", "mois", "année"])
                liste_annees = ["Toutes"]
            else:
                df_edit = df_h.copy().reset_index(drop=True)
                # Sécurité pour le format date
                df_edit['date'] = pd.to_datetime(df_edit['date'], dayfirst=True, errors='coerce')
                df_edit['année'] = df_edit['date'].dt.year.fillna(0).astype(int)
                liste_annees = ["Toutes"] + sorted(df_edit['année'].unique().astype(str).tolist(), reverse=True)

            df_f = df_edit.copy()
            
            # Filtrage (ne s'applique que si df_f n'est pas vide)
            if not df_f.empty:
                if st.session_state.filter_g != "Tous":
                    cps = [c for c,v in st.session_state.config_groupes.items() if v.get("Groupe") == st.session_state.filter_g]
                    df_f = df_f[df_f["compte"].isin(cps)]
                if st.session_state.filter_c != "Tous": 
                    df_f = df_f[df_f["compte"] == st.session_state.filter_c]
                if st.session_state.filter_a != "Toutes": 
                    df_f = df_f[df_f["année"] == int(st.session_state.filter_a)]
                if st.session_state.filter_m != "Tous": 
                    df_f = df_f[df_f["mois"] == st.session_state.filter_m]

            # --- 3. MISE EN PAGE (S'affiche dans tous les cas) ---
            col_large, col_main = st.columns([2, 4], gap="small")

            # --- COLONNE 1 : FILTRES & CATÉGORIES ---
            with col_large:
                col_cat, col_saisie = st.columns([1, 1.5])

                with col_cat: 
                    @st.fragment
                    def fragment_categorie():
                        st.markdown('<p style="font-weight:bold; margin-bottom:15px;">✨ Catégorie</p>', unsafe_allow_html=True)
                        
                        def valider_et_nettoyer():
                            emoji = st.session_state.get("emoji_choisi", "📁")
                            # On récupère la valeur depuis le widget
                            nom = st.session_state.get("input_new_cat", "").strip()
                            
                            if nom:
                                val_finale = f"{emoji} {nom}"
                                if sauvegarder_nouvelle_categorie_neon(val_finale, st.session_state.user):
                                    st.toast(f"✅ {val_finale} ajouté")
                                    
                                    # MISE À JOUR DE LA LISTE GLOBALE
                                    st.session_state.LISTE_categorieS_COMPLETE = charger_categories_neon_visibles(st.session_state.user)
                                    
                                    # --- ASTUCE POUR VIDER LE CHAMP ---
                                    # Au lieu de mettre à "" ici (ce qui provoque l'erreur), 
                                    # on va utiliser st.rerun() qui réinitialisera le widget.
                                    return True
                                else:
                                    st.error("Erreur ou doublon")
                            return False
                                
                            st.session_state.input_new_cat = ""
                        with st.container(border=True):
        # Popover compact avec onglets
                            with st.popover(f"Icône : {st.session_state.get('emoji_choisi', '📁')}", width='stretch'):
                                categories = {
                                    "🏠": ["🏠", "🔑", "🛋️", "🔌", "⚡", "💧", "📶", "🛡️"],
                                    "🛒": ["🛒", "🍱", "🍞", "🍳", "🍎", "🍼", "🧼", "📦"],
                                    "🍴": ["🍴", "☕", "🍺", "🍷", "🍦", "🍹", "🍿", "🍕"],
                                    "🚗": ["🚗", "⛽", "🚆", "🚲", "🚢", "🅿️", "🎫", "🚖"],
                                    "🎭": ["🎬", "🎮", "🏋️", "🎨", "🎤", "📸", "✈️", "🛍️"],
                                    "💸": ["💰", "💳", "🏦", "📈", "📉", "💶", "🔄", "💼"],
                                    "🌱": ["🏥", "💊", "🐱", "🐶", "🎁", "💈", "📚", "💎"]
                                }
                                
                                # Création des onglets (un par catégorie d'émojis)
                                tabs = st.tabs(list(categories.keys()))
                                
                                for idx, (cat_icon, icons) in enumerate(categories.items()):
                                    with tabs[idx]:
                                        # On affiche les 8 icônes sur deux lignes de 4 pour que ce soit très compact
                                        cols = st.columns(4) 
                                        for i, icon in enumerate(icons):
                                            # i % 4 permet de répartir sur les 4 colonnes
                                            if cols[i % 4].button(icon, key=f"emo_{idx}_{i}", width='stretch'):
                                                st.session_state.emoji_choisi = icon
                                                st.rerun(scope="fragment")

                            # Champ pour le nom
                            st.text_input("nom", placeholder="Ex: Essence...", label_visibility="collapsed", key="input_new_cat")

                            # Dans ton fragment_categorie, au niveau du bouton "Créer" :
                            if st.button("Créer la catégorie ✨", width='stretch', type="primary"):
                                if valider_et_nettoyer(): # Si ta fonction renvoie True
                                    relancer_avec_succes() # Relance toute la page pour mettre à jour les Selectbox du tableau

                    fragment_categorie()

                                    # --- DANS TON POPOVER ---
                    with st.popover("⚙️ Masquer catégories", width='stretch'):
                        # IMPORTANT : charger_categories_neon (SANS LE FILTRE VISIBLE)
                        toutes_les_cats = charger_categories_neon(st.session_state.user)
                        masquees_actuellement = charger_categories_neon_masquees(st.session_state.user)
                        
                        with st.form("form_masquage", border=False):
                            nouvelle_liste_masquee = []
                            
                            with st.container(height=300):
                                for cat in sorted(toutes_les_cats):
                                    # On coche si elle n'est PAS masquée
                                    est_deja_visible = cat not in masquees_actuellement
                                    
                                    # La checkbox affiche l'état actuel
                                    coché = st.checkbox(cat, value=est_deja_visible, key=f"pop_{cat}")
                                    
                                    # Si l'utilisateur décoche la case, on l'ajoute à la liste des masquées
                                    if not coché:
                                        nouvelle_liste_masquee.append(cat)
                            
                            if st.form_submit_button("Enregistrer", width='stretch', type="primary"):
                                if sauvegarder_preference_masquage_neon(st.session_state.user, nouvelle_liste_masquee):
                                    # On force la mise à jour de la liste filtrée dans le session_state
                                    st.session_state.LISTE_categorieS_COMPLETE = charger_categories_neon_visibles(st.session_state.user)
                                    st.toast("Préférences enregistrées ! ✨")
                                    st.rerun()
                
                
                
                # --- COLONNE 2 : AJOUT MANUEL & ACTIONS ---
                with col_saisie:
                    st.markdown("**💸 Plafonds & Budgets par catégories**", help="Fixez vos limites mensuelles pour chaque catégorie et suivez vos économies en temps réel")

                    user = st.session_state["user"]
                    
                    # On ouvre le formulaire ici pour tout englober
                    with st.form("global_budget_form", clear_on_submit=False):
                        
                        # 1. Sélecteurs de contexte (Mois et Compte)
                        c1, c2 = st.columns(2)
                        with c1:
                            m_cible = st.selectbox("Mois", ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"])
                        with c2:
                            liste_comptes = sorted([str(c) for c in st.session_state.df['compte'].unique().tolist() if pd.notna(c)])
                            c_cible = st.selectbox("Compte", liste_comptes)

                        # 2. Zone de saisie
                        col_cat, col_montant = st.columns([2, 1])
                        
                        with col_cat:
                            cat_choisie = st.selectbox(
                                "Catégorie à définir", 
                                [c for c in LISTE_categorieS_COMPLETE if c != "À catégoriser ❓"]
                            )
                        
                        with col_montant:
                            # Note : À l'intérieur du formulaire, cette valeur ne se mettra à jour 
                            # qu'APRES avoir cliqué sur Enregistrer ou si la page est déjà sur ce mois.
                            nouveau_montant = st.number_input("Budget (€)", step=10.0)

                        # 3. Bouton de validation unique
                        submitted = st.form_submit_button("💾 Enregistrer le budget", use_container_width=True, type="primary")

                        if submitted:
                            if enregistrer_ligne_budget_neon(user, m_cible, c_cible, cat_choisie, nouveau_montant):
                                st.cache_data.clear() # On vide le cache pour que le nouveau budget apparaisse partout
                                st.toast(f"Budget {cat_choisie} enregistré pour {m_cible} !", icon="✔️")
                                time.sleep(0.5)
                                st.rerun() # Seul ce bouton déclenche maintenant le refresh global


                                
                    
                if "indices_reel" not in st.session_state:
                            st.session_state.indices_reel = [0]
                with st.container():
                    
                    st.markdown('<p style="font-weight:bold; margin-bottom:-10px;">➕ Ajouter des opérations</p>', unsafe_allow_html=True)
                    # Définition du fragment pour isoler la zone de saisie
                    @st.fragment
                    def zone_saisie_multi():
                        # Récupération des options
                        options_comptes = list(st.session_state.config_groupes.keys()) if st.session_state.config_groupes else ["Défaut"]

                        st.markdown("""
                            <style>
                            /* On réduit la marge haute du formulaire pour qu'il ne soit pas trop loin du titre */
                            [data-testid="stForm"] {
                                margin-top: 0px !important;
                            }
                            /* Style pour les boutons de gestion en bas */
                            .stButton button { height: 40px !important; }
                            </style>
                        """, unsafe_allow_html=True)
                        
                        # Le formulaire englobe tout
                        with st.form("form_reel_multi", border=True):
                            ops_reelles = []
                            
                            # Affichage des lignes de saisie
                            container_lignes = st.container(height=250, border=False)
                            with container_lignes:
                                for idx in st.session_state.indices_reel:
                                    # Ligne 1 : Description et montant
                                    c1, c2, c_eur = st.columns([2, 0.8, 0.2])
                                    f_nom = c1.text_input("Description", key=f"r_n_{idx}", label_visibility="collapsed", placeholder="Description...")
                                    f_mnt = c2.number_input("montant", key=f"r_m_{idx}", label_visibility="collapsed", step=1.0, format="%.2f")
                                    c_eur.markdown("<p style='margin-top:7px; font-weight:bold; color:gray;'>€</p>", unsafe_allow_html=True)
                                    
                                    # Ligne 2 : compte, Catégorie, date
                                    c_cpte, c_cat, c_date = st.columns([1, 1, 1])
                                    f_compte = c_cpte.selectbox("compte", options_comptes, key=f"r_cp_{idx}", label_visibility="collapsed")
                                    f_cat = c_cat.selectbox("Cat", LISTE_categorieS_COMPLETE, key=f"r_cat_{idx}", label_visibility="collapsed")
                                    f_date = c_date.date_input("date", key=f"r_d_{idx}", label_visibility="collapsed")
                                    
                                    ops_reelles.append({
                                        "date": f_date.strftime('%d/%m/%Y'),
                                        "nom": f_nom, 
                                        "montant": f_mnt,
                                        "categorie": f_cat, 
                                        "compte": f_compte,
                                        "mois": nomS_mois[f_date.month - 1], 
                                        "année": f_date.year,
                                        "User": st.session_state["user"]
                                    })
                                    st.markdown("<hr style='margin:10px 0; opacity:0.1;'>", unsafe_allow_html=True)

                            # Bouton de validation (obligatoire dans un form)
                            submit_reel = st.form_submit_button("Enregistrer les opérations 🚀", width='stretch', type="primary")

                            # --- LOGIQUE DE SAUVEGARDE ---
                            if submit_reel:
                                valides = [o for o in ops_reelles if o["nom"].strip() != "" and o["montant"] != 0]
                                if valides:
                                    try:
                                        df_new_ops = pd.DataFrame(valides)
                                        df_existant = st.session_state.df.copy() if not st.session_state.df.empty else pd.DataFrame()
                                        df_total = pd.concat([df_existant, df_new_ops], ignore_index=True)
                                        
                                        # Nettoyage des dates
                                        df_total['date'] = pd.to_datetime(df_total['date'], dayfirst=True, format='mixed', errors='coerce')
                                        df_total = df_total.dropna(subset=['date'])
                                        df_total['date'] = df_total['date'].dt.strftime('%d/%m/%Y')
                                        
                                        if sauvegarder_donnees_neon(df_total, st.session_state["user"]):
                                            st.session_state.df = df_total
                                            st.session_state.indices_reel = [0]
                                            st.success(f"✅ {len(valides)} opérations ajoutées !")
                                            time.sleep(1)
                                            st.rerun() # Ici on reload toute la page pour mettre à jour le tableau à droite
                                    except Exception as e:
                                        st.error(f"Erreur : {e}")
                                else:
                                    st.warning("⚠️ Remplissez au moins une ligne.")

                        # --- BOUTONS DE GESTION (Hors du Form mais dans le Fragment) ---
                        # Comme on est dans un fragment, ces boutons ne rechargent QUE cette zone
                        cb1, cb2, cb3 = st.columns([1, 1, 1])
                        
                        if cb1.button("➕ Ligne", key="add_r", use_container_width=True):
                            st.session_state.indices_reel.append(max(st.session_state.indices_reel) + 1)
                            st.rerun(scope="fragment") # Recharge uniquement le fragment

                        if cb2.button("🗑️ Ligne", key="del_r", use_container_width=True):
                            if len(st.session_state.indices_reel) > 1:
                                st.session_state.indices_reel.pop()
                                st.rerun(scope="fragment")

                        if cb3.button("🔄 Reset", key="reset_r", use_container_width=True):
                            st.session_state.indices_reel = [0]
                            st.rerun(scope="fragment")

                    # Appel de la fonction
                    zone_saisie_multi()
                
                
            with col_main:  
                @st.fragment
                def zone_interactive_tableau():
                    # 1. INITIALISATION DES DONNÉES
                    if 'df' in st.session_state and not st.session_state.df.empty:
                        df_f = st.session_state.df.copy()
                    else:
                        st.info("Aucune donnée disponible.")
                        return

                    # 2. CRÉATION DES COLONNES À L'INTÉRIEUR DU FRAGMENT
                    # C'est ici que l'erreur est corrigée
                    col_sidebar, col_main_2 = st.columns([1, 4.5], gap="small")

                    # --- COLONNE DES FILTRES (Gauche) ---
                    with col_sidebar:
                        st.markdown('🔍 **Filtres**')

                        
                        with st.container(border=True):
                            st.markdown('Tri global')
                            # Filtre GROUPE
                            liste_g = ["Tous"] + st.session_state.groupes_liste
                            new_g = st.selectbox("Groupe", liste_g, 
                                                index=liste_g.index(st.session_state.filter_g) if st.session_state.filter_g in liste_g else 0,
                                                key="frag_filter_g")
                            
                            # Mise à jour immédiate pour le filtrage local
                            st.session_state.filter_g = new_g

                            # Reconstruction des comptes selon le groupe
                            comptes_detectes = sorted(df_f["compte"].unique().tolist()) if not df_f.empty else []
                            cps_filtre = ["Tous"] + (comptes_detectes if st.session_state.filter_g == "Tous" else [c for c,v in st.session_state.config_groupes.items() if v["Groupe"] == st.session_state.filter_g])
                            
                            new_c = st.selectbox("Compte", cps_filtre, 
                                                index=cps_filtre.index(st.session_state.filter_c) if st.session_state.filter_c in cps_filtre else 0,
                                                key="frag_filter_c")
                            st.session_state.filter_c = new_c

                            # Années et Mois
                            # 1. Ta liste d'options (reste identique)
                            liste_a = ["Toutes"] + sorted([str(int(a)) for a in df_f['année'].dropna().unique()], reverse=True)

                            # 2. Le selectbox
                            annee_selectionnee = st.selectbox("Année", liste_a, key="filter_a_select")

                            # 3. LE FILTRAGE (La correction est ici)
                            df_filtre = df_f.copy()

                            if annee_selectionnee != "Toutes":
                                # On convertit le choix du filtre ("2025") en entier (2025) pour matcher le DF
                                annee_num = int(annee_selectionnee)
                                df_filtre = df_filtre[df_filtre['année'] == annee_num]
                            
                            liste_m = ["Tous"] + nomS_mois
                            st.selectbox("Mois", liste_m, key="filter_m_select")

                                # --- 4. PRÉPARATION DE L'AFFICHAGE (Tri, Dates, etc.) ---
                            if not df_f.empty:
                                df_f['date'] = pd.to_datetime(df_f['date'], dayfirst=True, errors='coerce')
                                df_f['date_Affiche'] = df_f['date'].dt.strftime('%d/%m/%Y').fillna("⚠️ Erreur Format")
                                
                                # Tri initial
                                sort_order = st.session_state.get('sort_order', "↓ Décroissant")
                                ascending = (sort_order == "↑ Croissant")
                                df_f = df_f.sort_values(by="date", ascending=ascending)

                            st.markdown('Tri transactions')
                        # --- LOGIQUE DE TRI ---
                            # On définit d'abord les tris pour que df_f soit prêt
                            map_sort = {"📅 Date": "date", "🔤 Nom": "nom", "💰 Montant": "montant", "📂 Catégorie": "categorie"}
                            sort_label = st.selectbox("Trier par", list(map_sort.keys()), index=0, label_visibility="collapsed", key="sort_choice")
                            st.session_state.sort_by = map_sort[sort_label]
                            st.session_state.sort_order = st.selectbox("Ordre", ["↑ Croissant", "↓ Décroissant"], index=1, label_visibility="collapsed", key="sort_ord")

                            st.markdown('Supprimer transactions')
                            def toggle_all():
                                # On récupère la valeur de manière sécurisée avec .get()
                                # Si la clé n'existe pas, on prend False par défaut
                                val = st.session_state.get("master_control_v3", False)
                                
                                for idx in df_f.index:
                                    st.session_state[f"cb_v3_{idx}"] = val

                            st.checkbox("Tout sélectionner", key="master_control_v3", on_change=toggle_all)

                            # --- 2. CALCUL DES SÉLECTIONNÉS ---
                            # On regarde uniquement les checkboxes individuelles maintenant
                            indices_selectionnes = [idx for idx in df_f.index if st.session_state.get(f"cb_v3_{idx}", False)]
                            nb = len(indices_selectionnes)

                            # --- DANS TON FRAGMENT (afficher_tableau_transactions) ---

                            @st.dialog("Confirmer la suppression")
                            def confirmer_suppression(indices_selectionnes, df_f):
                                st.warning(f"Êtes-vous sûr de vouloir supprimer {len(indices_selectionnes)} transaction(s) ? Cette action est irréversible.")
                                
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.button("Annuler", use_container_width=True):
                                        st.rerun()
                                with col2:
                                    if st.button("Oui, supprimer", type="primary", use_container_width=True):
                                        with st.spinner("Suppression dans Neon..."):
                                            lignes_a_effacer = df_f.loc[indices_selectionnes]
                                            success = True
                                            try:
                                                with engine.begin() as conn:
                                                    for _, row in lignes_a_effacer.iterrows():
                                                        query = text("""
                                                            DELETE FROM transactions 
                                                            WHERE date = :date 
                                                            AND nom = :nom 
                                                            AND montant = :montant 
                                                            AND utilisateur = :utilisateur
                                                        """)
                                                        conn.execute(query, {
                                                            "date": row['date'],
                                                            "nom": row['nom'],
                                                            "montant": row['montant'],
                                                            "utilisateur": st.session_state.user
                                                        })
                                            except Exception as e:
                                                st.error(f"Erreur : {e}")
                                                success = False

                                            if success:
                                                # Mise à jour du DataFrame en session
                                                st.session_state.df = st.session_state.df.drop(index=indices_selectionnes).reset_index(drop=True)
                                                st.success("Transactions supprimées !")
                                                time.sleep(1)
                                                st.rerun()

                            if st.button(f"🗑️ Supprimer", type="primary", key="btn_del_v3", use_container_width=True):
                                if nb > 0:
                                    confirmer_suppression(indices_selectionnes, df_f)
                                else:
                                    st.error("Veuillez sélectionner au moins une transaction.")
                                                
                    


                    # 3. APPLICATION RÉELLE DES FILTRES SUR DF_F
                    if st.session_state.frag_filter_g != "Tous":
                        comptes_du_groupe = [c for c,v in st.session_state.config_groupes.items() if v["Groupe"] == st.session_state.filter_g]
                        df_f = df_f[df_f['compte'].isin(comptes_du_groupe)]
                    
                    if st.session_state.frag_filter_c != "Tous":
                        df_f = df_f[df_f['compte'] == st.session_state.frag_filter_c]
                        
                    if st.session_state.filter_a_select != "Toutes":
                        # On convertit le choix du widget (str) en entier (int)
                        annee_recherchee = int(st.session_state.filter_a_select)
                        # On filtre sur la colonne numérique
                        df_f = df_f[df_f['année'] == annee_recherchee]
                        
                    if st.session_state.filter_m_select != "Tous":
                        df_f = df_f[df_f['mois'] == st.session_state.filter_m_select]

                        

                    # --- COLONNE 3 : ÉDITION DU TABLEAU ---
                    with col_main_2:
                        # 1. INITIALISATION DES ÉTATS DE TRI
                        # Au lieu de regarder uniquement les catégories du DF, on utilise ta fonction officielle
                        if 'LISTE_categorieS_COMPLETE' not in st.session_state:
                            user = st.session_state.get("user", "Guest")
                            st.session_state.LISTE_categorieS_COMPLETE = charger_categories_neon_visibles(user)

                        if 'sort_by' not in st.session_state: st.session_state.sort_by = "date"
                        if 'sort_order' not in st.session_state: st.session_state.sort_order = "Descendant"
                        if 'df_temoin' not in st.session_state:
                            st.session_state.df_temoin = df_f['categorie'].to_dict()

                        if not df_f.empty:
                            # 1. On repart de la colonne brute si possible
                            # On force la conversion en précisant bien que le jour est en premier
                            df_f['date'] = pd.to_datetime(df_f['date'], dayfirst=True, errors='coerce')
                            
                            # 2. Si après ça on a encore des NaT, c'est que la donnée source dans le DF 
                            # était déjà corrompue au chargement. 
                            # ASTUCE : Vérifie si dans ton Google Sheet la colonne est bien au format "Texte brut"
                            
                            # 3. Création de l'affichage
                            df_f['date_Affiche'] = df_f['date'].dt.strftime('%d/%m/%Y').fillna("⚠️ Erreur Format")

                            # 4. Tri
                            ascending = (st.session_state.sort_order == "Ascendant")
                            df_f = df_f.sort_values(by="date", ascending=ascending)

                            # --- LOGS DES ERREURS (Dans la console) ---
                            invalides = df_f[df_f['date_Affiche'] == "⚠️ Invalide"]
                            if not invalides.empty:
                                print("\n❌ --- LOGS dateS INVALIDES ---")
                                for idx, row in invalides.iterrows():
                                    nom = row['nom']
                                    valeur_brute = row['date_Raw']
                                    type_brut = type(valeur_brute)
                                    print(f"Transaction: {nom} | Contenu Brut: '{valeur_brute}' | Type Python: {type_brut}")
                                print("-------------------------------\n")
                            
                        @st.fragment
                        def afficher_tableau_transactions(df_f):
                            

                            # Utilisation du style plus fin comme vu précédemment
                            st.markdown(f'<p style="font-size:18px; font-weight:bold; margin-top:5px;">📝 Édition ({len(df_f)})</p>', unsafe_allow_html=True)

                            # --- APPLICATION DU TRI ---
                            ascending = (st.session_state.sort_order == "↑ Croissant")
                            df_f = df_f.sort_values(by=st.session_state.sort_by, ascending=ascending)
                            # Utilisation de ratios IDENTIQUES à ceux des lignes du tableau
                            h_col1, h_col2, h_col3, h_col5, h_col4 = st.columns([2.5, 1.8, 1.5, 0.5, 0.5])

                            header_style = 'style="color:gray; font-size:11px; font-weight:bold; text-align:{align};"'

                            with h_col1:
                                st.markdown(f'<div {header_style.format(align="left")}>DÉTAILS</div>', unsafe_allow_html=True)
                            with h_col2:
                                st.markdown(f'<div {header_style.format(align="left")}>CATÉGORIE</div>', unsafe_allow_html=True)
                            with h_col3:
                                st.markdown(f'<div {header_style.format(align="left")}>MOIS</div>', unsafe_allow_html=True)
                            with h_col5:
                                st.markdown(f'<div {header_style.format(align="left")}>DIVISER</div>', unsafe_allow_html=True)
                            with h_col4:
                                st.markdown(f'<div {header_style.format(align="left")}>EFFACER</div>', unsafe_allow_html=True)

                            # Affiche dans la console (ou un st.write temporaire) les valeurs qui posent problème
                            debug_dates = df_f[df_f['date_Affiche'] == "⚠️ Format date"]
                            if not debug_dates.empty:
                                # Affiche le nom de la transaction et ce qui est écrit dans la colonne date originale
                                st.sidebar.write("Debug dates:", debug_dates[['nom', 'date']].head())

                            with st.container(height=570, border=True):
                                # 1. Crée une petite fonction de callback (à mettre au début de ton script ou avant le bloc d'édition)
                                def update_df_from_ui(index_global, key_widget, colonne):
                                # Cette fonction met à jour la source de vérité dès qu'un selectbox change
                                    if key_widget in st.session_state:
                                        nouvelle_valeur = st.session_state[key_widget]
                                        st.session_state.df.at[index_global, colonne] = nouvelle_valeur



                                for idx, row in df_f.iterrows():
                                    cat_value = row.get('categorie') or row.get('catégorie') or ""

                                    if "🔄" in str(cat_value):
                                        color_amount = "#9b59b6"
                                    else:
                                        color_amount = "#2ecc71" if row['montant'] > 0 else "#ff4b4b"
                                    
                                    c_info, c_cat, c_mois,c_split, c_del = st.columns([2.5, 1.8, 1.5,0.5, 0.5])
                                    
                                    with c_info:
                                        st.markdown(f'''
                                            <div style="border-left:3px solid {color_amount}; padding-left:8px; line-height:1.2;">
                                                <div style="font-weight:bold; font-size:12px;">{row["nom"]}</div>
                                                <div style="font-size:10px; color:gray;">{row["date_Affiche"]} • {row["compte"]}</div>
                                                <div style="font-weight:bold; color:{color_amount}; font-size:12px;">{row["montant"]:.2f} €</div>
                                            </div>
                                        ''', unsafe_allow_html=True)
                                    
                                    with c_cat:
                                        # --- PROTECTION DES CATÉGORIES MANUELLES ---
                                        current_cat = row.get('categorie', row.get('catégorie', 'Inconnu'))
                                        nom_transac = row['nom'] # On récupère le nom pour la comparaison
                                        
                                        # --- NOUVELLE FONCTIONNALITÉ : SUGGESTION PAR SIMILARITÉ ---
                                        suggestion = None
                                        nom_similaire = None
                                        
                                        # On ne cherche une suggestion que si la ligne n'est pas encore catégorisée
                                        if pd.isna(current_cat) or current_cat in ["", "À catégoriser ❓"]:
                                            # On cherche dans le DF global (st.session_state.df) des noms proches
                                            noms_connus = st.session_state.df[st.session_state.df['categorie'].notna()]['nom'].unique().tolist()
                                            from difflib import get_close_matches
                                            nom_a_chercher = str(nom_transac) if nom_transac is not None else ""

                                            # On filtre noms_connus pour enlever les éventuels None ou NaN qui font planter difflib
                                            noms_propres = [str(n) for n in noms_connus if pd.notna(n)]

                                            matches = get_close_matches(nom_a_chercher, noms_propres, n=1, cutoff=0.6)
                                            
                                            if matches:
                                                nom_similaire = matches[0]
                                                suggestion = st.session_state.df[st.session_state.df['nom'] == nom_similaire]['categorie'].iloc[0]

                                        # --- LOGIQUE EXISTANTE DES OPTIONS ---
                                        options_dynamiques = LISTE_categorieS_COMPLETE.copy()
                                        
                                        # Si on a une suggestion, on s'assure qu'elle est dans la liste
                                        if suggestion and suggestion not in options_dynamiques:
                                            options_dynamiques.append(suggestion)
                                            
                                        if current_cat not in options_dynamiques and pd.notna(current_cat):
                                            options_dynamiques.append(current_cat)
                                        
                                        options_dynamiques = sorted(list(set(options_dynamiques))) 

                                        # --- CALCUL DE L'INDEX PAR DÉFAUT ---
                                        # Si vide, on prend la suggestion, sinon la catégorie actuelle
                                        try:
                                            if (pd.isna(current_cat) or current_cat in ["", "À catégoriser ❓"]) and suggestion:
                                                idx_init = options_dynamiques.index(suggestion)
                                            else:
                                                idx_init = options_dynamiques.index(current_cat)
                                        except:
                                            idx_init = 0

                                        # 1. Création d'une clé unique basée sur les données de la ligne
                                        # On combine Nom + Date + Montant pour que la clé soit rattachée à LA transaction
                                        id_stable = f"{row['nom']}_{row['date']}_{row['montant']}"

                                        # 2. Affichage du Selectbox avec la nouvelle clé
                                        nouvelle_cat = st.selectbox(
                                            "C", 
                                            options=options_dynamiques, 
                                            index=idx_init, 
                                            key=f"cat_{id_stable}_{idx}", # <-- Clé stable + idx pour éviter les doublons parfaits
                                            label_visibility="collapsed",
                                            on_change=update_df_from_ui,
                                            args=(idx, f"cat_{id_stable}_{idx}", 'categorie') # <-- Ne pas oublier de mettre à jour la clé ici aussi
                                        )
                                        df_f.at[idx, 'categorie'] = nouvelle_cat
                                    
                                    with c_mois:
                                        st.selectbox(
                                            "M", 
                                            options=nomS_mois, 
                                            index=nomS_mois.index(row['mois']) if row['mois'] in nomS_mois else 0,
                                            key=f"mo_{idx}", 
                                            label_visibility="collapsed",
                                            # AJOUT DU CALLBACK ICI :
                                            on_change=update_df_from_ui,
                                            args=(idx, f"mo_{idx}", 'mois') 
                                        )
                                        

                                    with c_split:
                                        if st.button("✂️", key=f"split_{idx}", help="Diviser cette transaction en plusieurs parts",use_container_width=True):
                                            
                                            @st.dialog(f"Diviser : {row['nom']}")
                                            def multi_split_dialog(index_origine, row_data):
                                                total_a_diviser = float(row_data['montant'])
                                                st.write(f"montant total à répartir : **{total_a_diviser}€**")
                                                
                                                # 1. Choisir en combien de parts diviser
                                                nb_parts = st.number_input("nombre de parts", min_value=2, max_value=10, value=2)
                                                
                                                nouvelles_parts = []
                                                montant_cumule = 0.0
                                                
                                                st.divider()
                                                
                                                # 2. Générer les champs dynamiquement
                                                for i in range(int(nb_parts)):
                                                    st.markdown(f"**Part n°{i+1}**")
                                                    col_m, col_c = st.columns([1, 1])
                                                    
                                                    with col_m:
                                                        # Pour la dernière part, on calcule automatiquement le reste pour éviter les erreurs de calcul
                                                        if i == nb_parts - 1:
                                                            reste = round(total_a_diviser - montant_cumule, 2)
                                                            m_part = st.number_input(f"montant {i+1}", value=reste, disabled=True, key=f"m_{i}")
                                                        else:
                                                            m_part = st.number_input(f"montant {i+1}", value=round(total_a_diviser/nb_parts, 2), step=1.0, key=f"m_{i}")
                                                            montant_cumule += m_part
                                                    
                                                    with col_c:
                                                        c_part = st.selectbox(f"Catégorie {i+1}", options=LISTE_categorieS_COMPLETE, key=f"c_{i}")
                                                    
                                                    nouvelles_parts.append({"montant": m_part, "categorie": c_part})

                                                st.divider()
                                                
                                                # 3. Validation et Sauvegarde
                                                if st.button("Confirmer la division ✅", width='stretch', type="primary"):
                                                    df_temp = st.session_state.df.copy()
                                                    
                                                    # Création des nouvelles lignes basées sur l'originale
                                                    nouvelles_lignes = []
                                                    for part in nouvelles_parts:
                                                        nouvelle_ligne = row_data.copy()
                                                        nouvelle_ligne['montant'] = part['montant']
                                                        nouvelle_ligne['categorie'] = part['categorie']
                                                        # On peut optionnellement modifier le nom pour indiquer le split
                                                        nouvelle_ligne['nom'] = f"{row_data['nom']} (Part)"
                                                        nouvelles_lignes.append(nouvelle_ligne)
                                                    
                                                    # Mise à jour du DataFrame
                                                    df_temp = df_temp.drop(index_origine)
                                                    df_temp = pd.concat([df_temp, pd.DataFrame(nouvelles_lignes)], ignore_index=True)
                                                    
                                                    # Sauvegarde vers GSheets
                                                    sauvegarder_donnees_neon(df_temp, st.session_state.user)
                                                    st.session_state.df = df_temp
                                                    
                                                    st.success(f"Transaction divisée en {nb_parts} !")
                                                    time.sleep(1)
                                                    relancer_avec_succes()

                                            multi_split_dialog(idx, row)


                                    
                                    with c_del:
                                        st.checkbox(
                                            " ", 
                                            key=f"cb_v3_{idx}", 
                                            label_visibility="collapsed",
                                            on_change=refresh_sidebar  # <--- AJOUTEZ CECI
                                        )

                        # --- C. APPEL DE LA FONCTION ---
                        if not df_f.empty:
                            # On appelle la fonction une seule fois, au même niveau que sa définition
                            afficher_tableau_transactions(df_f)
                        else:
                            st.info("Aucune transaction à afficher.")        
                                
                                
                        with st.container(border=True):
                            c_save1, c_save2 = st.columns([1.5, 2])
                            with c_save1:
                                apprendre = st.checkbox("🧠 Mémoriser les catégories modifiées", value=False,help="Active l'apprentissage automatique : si vous renommez une catégorie, toutes les autres transactions portant exactement le même nom seront mises à jour avec cette nouvelle catégorie.")
                            
                            with c_save2:
                                if st.button("💾 Sauvegarder les modifications", type="primary", use_container_width=True):
                                    user_actuel = st.session_state.get("user")
                                    temoin = st.session_state.get("df_temoin", {})
                                    nouvelles_regles = []

                                    # --- 1. APPLICATION DES MODIFICATIONS ---
                                    for idx_f in df_f.index:
                                        row_f = df_f.loc[idx_f]
                                        
                                        # Reconstruction de l'ID stable (doit être IDENTIQUE à la selectbox)
                                        id_stable_f = f"{row_f['nom']}_{row_f['date']}_{row_f['montant']}"
                                        key_cat = f"cat_{id_stable_f}_{idx_f}"
                                        key_mo = f"mo_{id_stable_f}_{idx_f}" # Clé stable aussi pour le mois !

                                        # Mise à jour du mois
                                        if key_mo in st.session_state:
                                            st.session_state.df.at[idx_f, 'mois'] = st.session_state[key_mo]

                                        # Logique d'apprentissage
                                        if key_cat in st.session_state:
                                            cat_choisie = st.session_state[key_cat]
                                            cat_initiale = temoin.get(idx_f)

                                            # On compare même si l'initiale est None/NaN
                                            if str(cat_choisie) != str(cat_initiale):
                                                nom_op = row_f['nom']
                                                
                                                if apprendre:
                                                    nouvelles_regles.append((nom_op, cat_choisie))
                                                    # Cascade sur tout le DF
                                                    mask = st.session_state.df['nom'] == nom_op
                                                    st.session_state.df.loc[mask, 'categorie'] = cat_choisie
                                                else:
                                                    # Mise à jour simple si apprentissage décoché
                                                    st.session_state.df.at[idx_f, 'categorie'] = cat_choisie

                                    # --- 2. PRÉPARATION DE L'ENVOI (APRÈS LES MISES À JOUR) ---
                                    df_a_sauver = st.session_state.df.copy() # On copie APRÈS la cascade

                                    if nouvelles_regles:
                                        st.info(f"🧠 Apprentissage de {len(nouvelles_regles)} règle(s)...")
                                        sauvegarder_apprentissage_batch_neon(nouvelles_regles, user_actuel)
                                        if "df_temoin" in st.session_state:
                                            del st.session_state.df_temoin

                                    # --- 3. SAUVEGARDE NEON ---
                                    try:
                                        # Nettoyage des dates (format Neon)
                                        df_a_sauver['date'] = pd.to_datetime(df_a_sauver['date'], dayfirst=True, errors='coerce')
                                        df_a_sauver = df_a_sauver.dropna(subset=['date'])

                                        with st.spinner("Sauvegarde en cours..."):
                                            success = sauvegarder_donnees_neon(df_a_sauver, user_actuel)
                                            if success:
                                                st.cache_data.clear()
                                                st.success("✅ Modifications enregistrées !")
                                                time.sleep(1)
                                                st.rerun()
                                    except Exception as e:
                                        st.error(f"Erreur lors de la sauvegarde : {e}")

                zone_interactive_tableau()

                    
                                        
    elif selected == "Importer":                        
        # --- TAB IMPORT (VERSION CORRIGÉE ET SÉCURISÉE) ---
            st.markdown("""
                <div style="background-color: rgba(255, 255, 255, 0.05); padding: 20px; border-radius: 15px; border: 1px solid rgba(128, 128, 128, 0.1); margin-bottom: 25px;">
                    <h2 style="margin: 0; font-size: 24px;">📥 Importation des données</h2>
                    <p style="color: gray; font-size: 14px;">Glissez votre relevé bancaire au format CSV pour synchroniser vos comptes.</p>
                </div>
            """, unsafe_allow_html=True)

            col_config, col_upload = st.columns([1, 1.5], gap="large")
            
            with col_config:
                st.markdown("##### ⚙️ Configuration")
                with st.container(border=True):
                    c_mode = st.radio("Type de compte :", ["Existant", "Nouveau"], horizontal=True, label_visibility="collapsed")
                    
                    if c_mode == "Existant":
                        
                        
                        # --- 1. On récupère tous les noms de comptes connus (Transactions + Config) ---
                        comptes_transactions = st.session_state.df["compte"].unique().tolist() if not st.session_state.df.empty else []
                        
                        # --- 2. On récupère les comptes de la config GSheets (Session State) ---
                        comptes_config = list(st.session_state.config_groupes.keys())
                        
                        # Fusion propre sans doublons
                        liste_finale = sorted(list(set(comptes_transactions + comptes_config)))
                        
                        c_nom = st.selectbox("Choisir le compte :", liste_finale)
                        
                    else:
                        c_nom = st.text_input("nom du nouveau compte :", placeholder="Ex: Livret A")

                    stats_compte = st.session_state.df[st.session_state.df["compte"] == c_nom]
                    
                    if not stats_compte.empty:
                        st.markdown("---")
                        c_st1, c_st2 = st.columns(2)
                        
                        # --- CORRECTION ICI ---
                        # On convertit en datetime pour pouvoir trouver le max et formater
                        dates_converties = pd.to_datetime(stats_compte["date"], dayfirst=True, errors='coerce')
                        date_max = dates_converties.max()
                        
                        # On vérifie que la date n'est pas vide (NaT) avant de formater
                        derniere_date = date_max.strftime("%d/%m/%Y") if pd.notnull(date_max) else "Inconnue"
                        
                        c_st1.metric("Dernière opération", derniere_date)
                        c_st2.metric("Nb transactions", len(stats_compte))
                    
                    

            with col_upload:
                st.markdown("##### 📄 Fichier")
                f = st.file_uploader("Glissez le fichier ici", type="csv", key="file_up", label_visibility="collapsed")
                
                if f:
                    st.success(f"Fichier détecté : **{f.name}**")
                    # --- AJOUT : APERÇU RAPIDE ---
                    with st.expander("🔍 Aperçu rapide des 5 premières données brutes"):
                        try:
                            # On lit les premières lignes en texte brut pour détecter le séparateur
                            f.seek(0)
                            content = f.read().decode('latin-1') # Décodage sécurisé pour l'aperçu
                            lines = [l.strip() for l in content.splitlines() if l.strip()][:15]
                            
                            # On cherche la ligne d'en-tête comme dans ton code d'importation
                            header_line_idx = 0
                            for i, line in enumerate(lines):
                                l_low = line.lower()
                                if "date" in l_low and any(m in l_low for m in ["montant", "debit", "credit", "libellé"]):
                                    header_line_idx = i
                                    break
                            
                            # On détecte le séparateur sur la ligne d'en-tête
                            test_line = lines[header_line_idx]
                            sep = ';' if test_line.count(';') > test_line.count(',') else ','
                            
                            # On lit proprement le DataFrame à partir de la bonne ligne
                            df_preview = pd.read_csv(
                                io.StringIO("\n".join(lines[header_line_idx:])),
                                sep=sep,
                                nrows=5
                            )
                            st.dataframe(df_preview, use_container_width=True)
                            
                        except Exception as e_prev:
                            st.warning("Impossible d'afficher l'aperçu (format complexe), mais l'importation automatique peut quand même fonctionner.")
                        
                        f.seek(0) # Toujours remettre le curseur au début pour le bouton d'importation
                    
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🚀 Lancer l'importation automatique", width='content', type="primary"):
                    if not f:
                        st.error("Veuillez sélectionner un fichier.")
                    elif not c_nom or c_nom == "Aucun compte":
                        st.error("Veuillez nommer ou choisir un compte.")
                    else:
                        try:
                            with st.spinner("Analyse et catégorisation en cours..."):
                                st.cache_data.clear()
                                raw = f.read()
                                
                                # --- 1. DÉCODAGE ROBUSTE ---
                                contenu_csv = "" # Changé ici
                                for e in ['latin-1', 'utf-8', 'cp1252', 'utf-8-sig']:
                                    try: 
                                        contenu_csv = raw.decode(e) # Changé ici
                                        break
                                    except: continue

                                # Mise à jour de la ligne suivante aussi :
                                lines = [l.strip() for l in contenu_csv.splitlines() if l.strip()] # Changé ici
                                h_idx, sep = None, ','
                                
                                # --- 2. DÉTECTION DE L'EN-TÊTE ---
                                # On cherche la ligne qui contient "date" ET "nom" ou "montant"
                                for i, line in enumerate(lines[:20]):
                                    l_lower = line.lower()
                                    if "date" in l_lower and (any(m in l_lower for m in ["montant", "debit", "credit", "valeur"])):
                                        h_idx = i
                                        sep = ';' if line.count(';') > line.count(',') else ','
                                        break
                                
                                if h_idx is not None:
                                    # --- 3. LECTURE AVEC PARAMÈTRES FORCÉS ---
                                    df_n = pd.read_csv(
                                        io.StringIO("\n".join(lines[h_idx:])), # Utilise bien 'lines' qui vient de 'contenu_csv'
                                        sep=sep, 
                                        engine='python',
                                        on_bad_lines='skip',
                                        skip_blank_lines=True
                                    )
                                    
                                    # Nettoyage radical des colonnes
                                    df_n.columns = [str(c).strip() for c in df_n.columns]
                                    df_n = df_n.loc[:, ~df_n.columns.duplicated()].copy()
                                    
                                    # --- 4. REnomMAGE ---
                                    for std, syns in CORRESPONDANCE.items():
                                        for col in df_n.columns:
                                            if col in syns or col.lower() in [s.lower() for s in syns]: 
                                                df_n = df_n.rename(columns={col: std})
                                    
                                    # --- 5. VÉRIFICATION ET TRAITEMENT ---
                                    cols = df_n.columns.tolist()
                                    
                                    # On vérifie si on a les données minimales
                                    if "date" in cols:
                                        # Conversion date
                                        d_col = df_n["date"].iloc[:, 0] if isinstance(df_n["date"], pd.DataFrame) else df_n["date"]
                                        df_n["date_C"] = pd.to_datetime(d_col.astype(str), dayfirst=True, errors='coerce')
                                        df_n = df_n.dropna(subset=["date_C"])
                                        
                                        # Détection montant
                                        if "Debit" in cols and "Credit" in cols:
                                            c1 = df_n["Credit"].apply(clean_montant_physique).fillna(0)
                                            c2 = df_n["Debit"].apply(clean_montant_physique).fillna(0)
                                            df_n["M_Final"] = c1 - c2.abs()
                                        elif "montant" in cols:
                                            df_n["M_Final"] = df_n["montant"].apply(clean_montant_physique)
                                        else:
                                            st.error(f"Colonnes trouvées : {cols}. Vérifiez votre fichier CSV.")
                                            st.stop()

                                        # Détection nom
                                        n_col = "nom" if "nom" in cols else (cols[1] if len(cols) > 1 else cols[0])
                                        

                                        # --- 6. CRÉATION DU DF FINAL ---
                                        df_res = pd.DataFrame({
                                            "date": df_n["date_C"], 
                                            "nom": df_n[n_col].astype(str).apply(simplifier_nom_definitif),
                                            "montant": df_n["M_Final"], 
                                            "compte": [c_nom] * len(df_n)
                                        })

        

                                        # --- MODIFICATION ICI : On utilise df_n pour avoir accès à TOUTES les colonnes ---
                                        df_res["categorie"] = df_n.apply(
                                            lambda row: categoriser(row[n_col], row["M_Final"], c_nom, row), 
                                            axis=1
                                        )

                                        df_res["mois"] = df_res["date"].dt.month.map(lambda x: nomS_mois[int(x)-1])
                                        df_res["année"] = df_res["date"].dt.year
                                        
                                        # --- SAUVEGARDE ET SYNCHRONISATION ---

                                        # 1. On récupère les données déjà présentes dans le Google Sheet
                                        try:
                                            df_existant = charger_donnees(st.session_state["user"])
                                        except:
                                            df_existant = pd.DataFrame()

                                        # --- 4. PRÉPARATION POUR GOOGLE SHEETS (VERSION NETTOYÉE) ---
                                        try:
                                            # On prépare le DataFrame final (fusion existant + nouveau)
                                            if not df_existant.empty:
                                                df_final = pd.concat([df_existant, df_res], ignore_index=True)
                                            else:
                                                df_final = df_res

                                            # SÉCURITÉ : On s'assure que 'date' est bien au format datetime avant l'envoi
                                            # On utilise dayfirst=True car ton CSV est en format français
                                            df_final['date'] = pd.to_datetime(df_final['date'], dayfirst=True, errors='coerce')
                                            
                                            # On retire les lignes où la date n'a pas pu être lue
                                            df_final = df_final.dropna(subset=['date'])

                                            # --- 5. SAUVEGARDE ---
                                            # On envoie le DataFrame PROPRE (avec des objets dates) à la fonction.
                                            # C'EST CETTE FONCTION QUI GÉRERA LES DOUBLONS ET LE FORMAT ISO FINAL.
                                            sauvegarder_donnees_neon(df_final, st.session_state["user"])
                                            
                                            # MISE À JOUR LOCALE
                                            st.cache_data.clear()
                                            st.session_state.df = charger_donnees(st.session_state["user"])
                                            
                                            st.toast("✅ Données synchronisées avec succès !", icon="🚀")
                                            
                                            # Stats pour le résumé
                                            st.session_state.dernier_import_stats = {
                                                "nb": len(df_res),
                                                "dep": df_res[df_res['montant'] < 0]['montant'].sum(),
                                                "rev": df_res[df_res['montant'] > 0]['montant'].sum(),
                                                "compte": c_nom,
                                                "date": datetime.now().strftime("%H:%M")
                                            }
                                            
                                            time.sleep(1)
                                            relancer_avec_succes()

                                        except Exception as e_save:
                                            st.error(f"Erreur lors de la préparation des données : {e_save}")

                                        
                                    else:
                                        st.error(f"Structure non reconnue. Colonnes lues : {cols}")
                                else:
                                    st.error("Impossible de trouver la ligne d'en-tête (date, montant...).")

                        except Exception as e:
                            st.error(f"❌ Erreur critique : {e}")


                # --- AFFICHAGE DU compte-RENDU (Permanent après import) ---
                if st.session_state.dernier_import_stats:
                    stats = st.session_state.dernier_import_stats
                    
                    st.markdown("---")
                    st.markdown(f"### 📊 Résumé du dernier import ({stats['date']})")
                    
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns(4)
                        
                        c1.metric("compte cible", stats['compte'])
                        c2.metric("Opérations ajoutées", f"+{stats['nb']}")
                        
                        # On affiche les dépenses en négatif rouge
                        c3.metric("Total Dépenses", f"{abs(stats['dep']):.2f} €", delta="-", delta_color="inverse")
                        
                        # On affiche les revenus en positif vert
                        c4.metric("Total Revenus", f"{stats['rev']:.2f} €", delta="+")

                    if st.button("Effacer le résumé", icon="🗑️"):
                        st.session_state.dernier_import_stats = None
                        relancer_avec_succes()

                # --- SECTION AIDE À L'IMPORTATION ---
                with st.popover("❓ Aide à l'exportation CSV"):
                    st.markdown("##### Guide par banque")
                    st.write("Choisissez votre banque pour voir la marche à suivre :")
                    
                    # Création des onglets à l'intérieur du popover
                    t1, t2, t3 = st.tabs(["La Banque Postale", "Revolut", "Banque Populaire"])
                    
                    with t1:
                        st.markdown("""
                        1. Connectez-vous à votre espace **LBP**.
                        2. Cliquez sur le compte concerné.
                        3. Allez dans l'onglet **'Opérations'** ou **'Historique'**.
                        4. Cherchez l'icône de téléchargement ou le bouton **'Télécharger'**.
                        5. Choisissez le format **CSV** et la période souhaitée.
                        """)
                    
                    with t2:
                        st.markdown("""
                        1. Ouvrez l'application **Revolut** (ou le site web).
                        2. Sélectionnez votre compte (ex: Euro).
                        3. Cliquez sur le bouton **'Détails'** ou les trois petits points **(...)**.
                        4. Sélectionnez **'Relevé'**.
                        5. Choisissez **'Excel'** ou **'CSV'** et définissez la période.
                        """)
                        
                    with t3:
                        st.markdown("""
                        1. Connectez-vous à votre espace **Banque Populaire**.
                        2. Allez dans la section **'comptes'** puis **'Mes opérations'**.
                        3. Cliquez sur le bouton **'Exporter'** (souvent en haut à droite).
                        4. Sélectionnez le format **CSV** (parfois appelé 'Format tableur').
                        5. Validez pour lancer le téléchargement.
                        """)

                    st.caption("⚠️ Assurez-vous que le fichier contient bien les colonnes date, nom/libellé et montant.")


                    
    elif selected == "Tricount":
        st.header("🤝 Tricount")



        @st.dialog("✏️ Renommer le groupe")
        def dialogue_renommer_groupe(ancien_nom):
            nouveau_nom = st.text_input("Nouveau nom du groupe", value=ancien_nom)
            st.info(f"Toutes les dépenses de '{ancien_nom}' seront transférées vers '{nouveau_nom}'.")
            
            if st.button("Confirmer le changement", use_container_width=True, key=f"conf_rename_{ancien_nom}"):
                if nouveau_nom and nouveau_nom.strip() != ancien_nom:
                    nouveau_nom = nouveau_nom.strip()
                    
                    try:
                        # On ouvre une connexion via ton engine
                        with engine.begin() as conn: # .begin() gère le commit automatiquement
                            query = text("""
                                UPDATE tricount
                                SET groupe = :nouveau 
                                WHERE groupe = :ancien 
                                AND utilisateur = :user
                            """)
                            
                            conn.execute(
                                query, 
                                {
                                    "nouveau": nouveau_nom, 
                                    "ancien": ancien_nom, 
                                    "user": st.session_state["user"]
                                }
                            )
                        
                        st.success(f"Base Neon mise à jour : '{nouveau_nom}' !")
                        
                        # On vide le cache pour que le prochain st.rerun lise les nouvelles données
                        st.cache_data.clear()
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Erreur SQL : {e}")
                else:
                    st.warning("Veuillez saisir un nom différent.")
        

        @st.fragment
        def formulaire_saisie_depense(groupe_choisi, key_suffix):
            st.markdown("### ➕ Nouvelle dépense")
            
            # --- LA CORRECTION EST ICI ---
            # On récupère la liste spécifique à ce groupe
            cle_liste_membres = f"participants_{groupe_choisi}"
            membres_du_groupe = st.session_state.get(cle_liste_membres, [])
            
            if not membres_du_groupe:
                st.warning("⚠️ Aucun membre dans ce groupe. Ajoutez des membres à gauche d'abord.")
                return # On arrête la fonction ici si le groupe est vide
            # -----------------------------

            with st.container(border=True):
                libelle = st.text_input("libellé", placeholder="Restaurant, Courses...", key=f"libelle_{key_suffix}")
                montant_total = st.number_input("montant Total (€)", min_value=0.0, step=0.01, key=f"montant_{key_suffix}")
                
                # On utilise membres_du_groupe au lieu de st.session_state.participants
                payeur = st.selectbox("Qui a payé ?", membres_du_groupe, key=f"select_p_{key_suffix}")
                
                st.markdown("**Qui consomme ?**")
                p_concernes = st.multiselect(
                    "Sélectionner les participants", 
                    membres_du_groupe, # Ici aussi
                    default=membres_du_groupe, # Et ici
                    key=f"multi_p_{key_suffix}"
                )
                
                # --- CALCUL ET AFFICHAGE DE LA PART ÉQUITABLE ---
                nb_p = len(p_concernes)
                if nb_p > 0 and montant_total > 0:
                    part_equitable = montant_total / nb_p
                    st.info(f"💡 **Division équitable : {part_equitable:.2f}€** par personne")
                elif nb_p == 0 and montant_total > 0:
                    st.warning("⚠️ Sélectionnez au moins une personne pour diviser.")

                st.markdown("**Ajustement des parts :**")
                parts_saisies = {}
                
                nb_p = len(p_concernes)
                if nb_p > 0:
                    cols = st.columns(2)
                    for idx, p in enumerate(p_concernes):
                        with cols[idx % 2]:
                            parts_saisies[p] = st.number_input(
                                f"Part de {p}", 
                                min_value=0.0, 
                                # Utilisation de la liste filtrée pour les calculs
                                value=montant_total / nb_p if nb_p > 0 else 0.0,
                                step=0.01, 
                                key=f"input_part_{p}_{key_suffix}" 
                            )
                
                # Vérification de l'équilibre des centimes
                somme_parts = sum(parts_saisies.values())
                diff = round(montant_total - somme_parts, 2)

                if montant_total > 0 and nb_p > 0:
                    if abs(diff) < 0.01:
                        st.success("✅ Total parfaitement réparti !")
                    else:
                        st.warning(f"Reste à répartir : **{diff}€**")

                # Bouton d'enregistrement
                if st.button("Enregistrer la dépense 💾", use_container_width=True, type="primary",key=f"save_{key_suffix}"):
                    if montant_total <= 0 or nb_p == 0 or abs(diff) > 0.01:
                        st.error("Veuillez vérifier le montant et la répartition.")
                    else:
                        repartition_str = ",".join([f"{p}:{val}" for p, val in parts_saisies.items()])
                        
                        nouvelle_depense = {
                            "date": datetime.now().strftime("%d/%m/%Y"),
                            "libellé": libelle,
                            "payé_par": payeur,
                            "pour_qui": repartition_str,
                            "montant": montant_total,
                            "groupe": groupe_choisi,
                            "utilisateur": st.session_state["user"]
                        }
                        
                        if sauvegarder_transaction_tricount_neon(nouvelle_depense):
                            st.success("Dépense ajoutée !")
                            st.cache_data.clear()
                            st.rerun()

            

        # --- DIALOGUE DE SUPPRESSION ---
        @st.dialog("⚠️ Supprimer le groupe")
        def dialogue_suppression_groupe(groupe_a_supprimer):
            st.warning(f"Es-tu sûr de vouloir supprimer le groupe **{groupe_a_supprimer}** ?")
            st.info("Cette action supprimera toutes les dépenses liées à ce groupe dans la base Neon.")
            
            if st.button("OUI, TOUT SUPPRIMER", use_container_width=True, type="primary"):
                try:
                       
                    
                    # Suppression ciblée : Uniquement les dépenses du groupe de l'utilisateur
                    query = text("""
                        DELETE FROM tricount 
                        WHERE "groupe" = :g AND "utilisateur" = :u
                    """)
                    
                    with engine.begin() as conn_sql:
                        conn_sql.execute(query, {
                            "g": groupe_a_supprimer,
                            "u": st.session_state["user"]
                        })
                    
                    st.success(f"Le groupe '{groupe_a_supprimer}' a été supprimé !")
                    st.cache_data.clear()
                    
                    # On force le retour à l'accueil du Tricount
                    time.sleep(1)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Erreur lors de la suppression Neon : {e}")


        @st.dialog("✏️ Modifier la transaction")
        def modifier_transaction(row):
            # 1. On récupère le nom du groupe directement depuis la ligne (row)
            nom_groupe = row['groupe']
            cle_membres = f"participants_{nom_groupe}"
            
            # 2. On récupère les membres de CE groupe
            # Si la clé n'existe pas, on essaie de la recharger
            membres_du_groupe = st.session_state.get(cle_membres, [])
            
            if not membres_du_groupe:
                st.error("Impossible de retrouver les membres de ce groupe.")
                return

            st.markdown(f"**Groupe :** {nom_groupe}")
            
            # Préparation du dictionnaire des parts actuelles
            parts_actuelles = {}
            for item in str(row['pour_qui']).split(','):
                if ':' in item:
                    n, v = item.split(':')
                    parts_actuelles[n.strip()] = float(v)

            with st.form("form_edit_tricount", border=False):
                new_libelle = st.text_input("Libellé", value=row['libellé'])
                new_montant = st.number_input("Montant Total (€)", value=float(row['montant']), min_value=0.01, step=0.01)
                
                # 3. Utilisation de la bonne liste pour le payeur
                try:
                    idx_payeur = membres_du_groupe.index(row['payé_par'])
                except:
                    idx_payeur = 0
                    
                new_payeur = st.selectbox("Qui a payé ?", membres_du_groupe, index=idx_payeur)

                st.divider()
                st.markdown("💰 **Ajuster les parts :**")
                
                new_parts = {}
                cols = st.columns(2)
                # 4. Utilisation de la bonne liste pour les parts
                for i, p in enumerate(membres_du_groupe):
                    val_defaut = parts_actuelles.get(p, 0.0)
                    with cols[i % 2]:
                        # Note: ici pas besoin de key_suffix car st.form isole les IDs des widgets
                        new_parts[p] = st.number_input(f"Part de {p}", min_value=0.0, value=val_defaut, step=0.01)

                submit = st.form_submit_button("Enregistrer les modifications", use_container_width=True, type="primary")

            if submit:
                total_parts = sum(new_parts.values())
                if abs(total_parts - new_montant) > 0.01:
                    st.error(f"❌ Erreur : La somme des parts ({total_parts:.2f}€) ≠ Total ({new_montant:.2f}€)")
                else:
                    repartition_str = ",".join([f"{p}:{val}" for p, val in new_parts.items() if val > 0])
                    
                    donnees_maj = {
                        "libellé": new_libelle,
                        "montant": new_montant,
                        "payé_par": new_payeur,
                        "pour_qui": repartition_str
                    }
                    
                    if mettre_a_jour_transaction_tricount_neon(row['id'], donnees_maj):
                        st.success("C'est à jour ! 🚀")
                        st.cache_data.clear()
                        st.rerun()

                

        

        # --- 1. DÉFINITIONS DES LOGIQUES (En haut de ton fichier, hors de tout if/boucle) ---

        def rafraichir_membres(df, groupe):
            membres = set()
            if not df.empty and groupe != "-- Choisir un groupe --":
                df_g = df[df['groupe'] == groupe]
                if not df_g.empty:
                    membres.update(df_g['payé_par'].unique())
                    for pq in df_g['pour_qui'].dropna():
                        for item in str(pq).split(','):
                            if ':' in item:
                                nom = item.split(':')[0]
                                membres.update([nom])
            return [m for m in membres if m not in ["Système", st.session_state.get("user", "") + "_init"]]

        @st.dialog("➕ Créer un nouveau groupe")
        def dialogue_creation_groupe(): # Plus besoin de passer df_tri ici
            nom_nouveau = st.text_input("Nom du voyage ou du projet")
            if st.button("Confirmer la création"):
                if nom_nouveau:
                    data_init = {
                        "date": datetime.now().strftime("%d/%m/%Y"),
                        "libellé": "Initialisation du groupe",
                        "payé_par": "Système",
                        "pour_qui": "Système:0",
                        "montant": 0.0,
                        "groupe": nom_nouveau,
                        "utilisateur": st.session_state["user"]
                    }
                    if sauvegarder_transaction_tricount_neon(data_init):
                        st.success(f"Groupe '{nom_nouveau}' créé !")
                        st.cache_data.clear()
                        st.rerun()

        # --- 2. LE FRAGMENT PRINCIPAL (L'interface) ---

        @st.fragment
        def afficher_espace_tricount():
            # 1. RÉCUPÉRATION DES DONNÉES
            df_tri = charger_tricount_neon(st.session_state["user"])
            groupes_existants = sorted(df_tri['groupe'].unique().tolist()) if not df_tri.empty else []

            if st.button("➕ Nouveau groupe", use_container_width=False):
                                dialogue_creation_groupe()
            if not groupes_existants:
                st.info("Créez votre premier groupe pour commencer !")
                groupe_choisi = "-- Choisir un groupe --"
            else:

                # Injection CSS pour agrandir le texte des onglets
                st.markdown("""
                    <style>
                        /* Cible le texte à l'intérieur des boutons d'onglets */
                        .stTabs [data-baseweb="tab"] p {
                            font-size: 20px; /* Ajuste la taille ici */
                            font-weight: bold; /* Optionnel : pour mettre en gras */
                        }
                    </style>
                """, unsafe_allow_html=True)
                # Création des onglets
                choix_tab = st.tabs(groupes_existants)
                
                # LOGIQUE D'AFFICHAGE : On boucle sur chaque onglet
                for i, tab in enumerate(choix_tab):
                    with tab:
                        # ICI, groupe_choisi correspondra bien à l'onglet sélectionné
                        groupe_choisi = groupes_existants[i]
                        
                        # --- GESTION DES PARTICIPANTS ---
                        # On rafraîchit si on change de groupe
                        if st.session_state.get('last_group') != groupe_choisi:
                            st.session_state.participants = rafraichir_membres(df_tri, groupe_choisi)
                            st.session_state.last_group = groupe_choisi

                        c_del, c_edit= st.columns(2)
                
                        with c_del:
                           if st.button("🗑️ Supprimer ce groupe", use_container_width=True, key=f"del_grp_{groupe_choisi}"):
                                dialogue_suppression_groupe(groupe_choisi)
                                
                        with c_edit:
                           if st.button("✏️ Renommer le groupe",use_container_width=True, key=f"rename_btn_{groupe_choisi}"):
                                # On passe BIEN les deux arguments : le DataFrame ET le nom du groupe
                                dialogue_renommer_groupe(groupe_choisi)

                            

                        # --- MISE EN PAGE SUR 4 COLONNES ---
                        col_membres, col_saisie, col_bilan, col_histo = st.columns([0.8, 1, 1.8, 1.8], gap="medium")
                        

                    
                        with col_membres:

                            # On crée un dictionnaire : {'Nom': 'Emoji'} basé sur les données SQL
                            mapping_emojis = {}
                            if not df_tri.empty and 'emoji' in df_tri.columns:
                                # On filtre sur le groupe actuel et on enlève les doublons pour avoir un dictionnaire propre
                                df_emojis = df_tri[df_tri['groupe'] == groupe_choisi].drop_duplicates('payé_par')
                                mapping_emojis = dict(zip(df_emojis['payé_par'], df_emojis['emoji']))


                            st.markdown("### 👥 Membres")
                            
                            # 1. Clé unique par groupe
                            cle_participants = f"participants_{groupe_choisi}"
                            
                            # 2. Initialisation
                            if cle_participants not in st.session_state:
                                st.session_state[cle_participants] = rafraichir_membres(df_tri, groupe_choisi)

                            # Champ de saisie
                            new_p = st.text_input(
                                "nom du membre", 
                                key=f"input_new_p_{groupe_choisi}",
                                label_visibility="collapsed", 
                                placeholder="Ex: Alex, Marie..."
                            )
                            
                            # Bouton Ajouter
                            if st.button("➕ Ajouter au groupe", use_container_width=True, key=f"btn_add_{groupe_choisi}"):
                                if new_p:
                                    nom = new_p.strip()
                                    if nom not in st.session_state[cle_participants]:
                                        st.session_state[cle_participants].append(nom)
                                        st.rerun()
                                    else:
                                        st.warning("Ce membre est déjà dans la liste.")

                            st.markdown("---")

                            # 3. UNE SEULE BOUCLE D'AFFICHAGE (La bonne !)
                            liste_actuelle = st.session_state[cle_participants]

                            if not liste_actuelle:
                                st.info("☝️ Ajoutez des membres pour commencer.")
                            else:
                                # On utilise enumerate pour plus de sécurité, mais la clé basée sur 'p' suffit
                                for i, p in enumerate(liste_actuelle):
                                    c_name, c_del = st.columns([4, 1])
                                    with c_name:
                                        with c_name:
                                            # --- RÉCUPÉRATION DE L'EMOJI ---
                                            # On regarde dans le dictionnaire créé plus haut
                                            emo = mapping_emojis.get(p, "👤")
                                            # Sécurité si la valeur est None ou NaN
                                            if not emo or str(emo) == 'nan':
                                                emo = "👤"
                                            
                                            st.write(f"{emo} **{p}**") # L'émoji s'affiche maintenant ici !
                                        
                                        
                                    with c_del:
                                        # On utilise une clé TRÈS spécifique : index + nom + groupe
                                        if st.button("❌", key=f"del_{i}_{p}_{groupe_choisi}"):
                                            st.session_state[cle_participants].pop(i)
                                            st.rerun()

                        # --- COLONNE 2 : FORMULAIRE DE SAISIE ---
                        with col_saisie:
                            formulaire_saisie_depense(groupe_choisi,key_suffix=groupe_choisi)
                        # --- COLONNE 3 : BILAN ET REMBOURSEMENTS ---
                        with col_bilan:
                            st.markdown("### 💵 BILAN DES REMBOURSEMENTS")

                            if not df_tri.empty:
                                df_groupe = df_tri[df_tri['groupe'] == groupe_choisi]
                                participants = st.session_state.participants

                                # --- INITIALISATION DES EMOJIS (si pas déjà fait) ---
                                if "emojis_membres" not in st.session_state:
                                    st.session_state.emojis_membres = {}
                                
                                for p in participants:
                                    if p not in st.session_state.emojis_membres:
                                        st.session_state.emojis_membres[p] = "👤" # Emoji par défaut
                                
                                # 1. CALCUL DES DETTES BRUTES
                                dettes_brutes = {p1: {p2: 0.0 for p2 in participants} for p1 in participants}
                                for _, row in df_groupe.iterrows():
                                    payeur = str(row['payé_par']).strip()
                                    if payeur == "Système": continue
                                    parts = str(row['pour_qui']).split(',')
                                    for part in parts:
                                        if ':' in part:
                                            benef, montant = part.split(':')
                                            benef = benef.strip()
                                            montant = float(montant)
                                            if benef != payeur:
                                                dettes_brutes[benef][payeur] += montant

                                # 2. LOGIQUE DE COMPENSATION (NETTING)
                                transferts_finaux = [] # Liste pour le PDF Global
                                dettes_par_personne = {p: [] for p in participants} # Pour les PDF Individuels

                                for i, p1 in enumerate(participants):
                                    for j, p2 in enumerate(participants):
                                        if i >= j: continue 
                                        
                                        d1_vers_2 = dettes_brutes[p1][p2]
                                        d2_vers_1 = dettes_brutes[p2][p1]
                                        
                                        if d1_vers_2 > d2_vers_1:
                                            diff = round(d1_vers_2 - d2_vers_1, 2)
                                            if diff > 0.01:
                                                transferts_finaux.append({'de': p1, 'a': p2, 'montant': diff})
                                                dettes_par_personne[p1].append(f"Doit {diff}€ à {p2}")
                                        elif d2_vers_1 > d1_vers_2:
                                            diff = round(d2_vers_1 - d1_vers_2, 2)
                                            if diff > 0.01:
                                                transferts_finaux.append({'de': p2, 'a': p1, 'montant': diff})
                                                dettes_par_personne[p2].append(f"Doit {diff}€ à {p1}")


                                if transferts_finaux:
                                    # Création des deux colonnes principales
                                    col_gauche, col_droite = st.columns(2)
                                    
                                    for idx, p in enumerate(participants):
                                        # On choisit la colonne en fonction de l'index (alternance gauche/droite)
                                        cible = col_gauche if idx % 2 == 0 else col_droite
                                        
                                        with cible:
                                            # Préparation des données
                                            a_donner = [t for t in transferts_finaux if t['de'] == p]
                                            a_recevoir = [t for t in transferts_finaux if t['a'] == p]
                                            
                                            total_donne = sum(t['montant'] for t in a_donner)
                                            total_recu = sum(t['montant'] for t in a_recevoir)
                                            solde_final = total_recu - total_donne

                                            ligne_p = df_groupe[df_groupe['payé_par'] == p]
                                            emoji_db = "👤" # Par défaut
                                            if not ligne_p.empty and 'emoji' in df_tri.columns:
                                                val = ligne_p.iloc[0]['emoji']
                                                emoji_db = val if val and str(val) != 'nan' else "👤"

                                            # --- CONTAINER INDIVIDUEL AVEC SÉLECTEUR D'EMOJI ---
                                            with st.container(border=True):
                                                c1, c2 = st.columns([1.5, 1])
                                                with c1:
                                                    ce1, ce2 = st.columns([1, 1.5])
                                                    with ce1:
                                                        # --- POPOVER AVEC SAUVEGARDE SQL ---
                                                        with st.popover(emoji_db):
                                                            choix = ["👨", "👩", "🧔", "👱‍♀️", "👵", "👴", "👩🏽‍🦱", "👨🏽‍🦱", "👦🏽", "👩🏽"]
                                                            cols_pop = st.columns(4)
                                                            for i_e, e in enumerate(choix):
                                                                if cols_pop[i_e % 4].button(e, key=f"sql_emo_{p}_{i_e}"):
                                                                    try:
                                                                        with engine.begin() as conn:
                                                                            # On met à jour toutes les transactions de ce membre pour ce groupe
                                                                            conn.execute(text("""
                                                                                UPDATE "tricount"
                                                                                SET emoji = :emo
                                                                                WHERE payé_par = :nom 
                                                                                AND groupe = :grp
                                                                                AND utilisateur = :user
                                                                            """), {"emo": e, "nom": p, "grp": groupe_choisi, "user": st.session_state["user"]})
                                                                        
                                                                        st.cache_data.clear()
                                                                        st.rerun()
                                                                    except Exception as ex:
                                                                        st.error(f"Erreur SQL : {ex}")
                                                    with ce2:
                                                        st.markdown(f"#### {p}")
                                                
                                                # Badge de solde
                                                if solde_final > 0:
                                                    c2.markdown(f"<div style='text-align:right; color:#00D166; font-weight:bold;'>+{solde_final:.2f}€</div>", unsafe_allow_html=True)
                                                elif solde_final < 0:
                                                    c2.markdown(f"<div style='text-align:right; color:#FF4B4B; font-weight:bold;'>{solde_final:.2f}€</div>", unsafe_allow_html=True)
                                                else:
                                                    c2.markdown(f"<div style='text-align:right; color:gray;'>Quitte</div>", unsafe_allow_html=True)


                                                # Détail des mouvements
                                                if a_donner:
                                                    for t in a_donner:
                                                        st.markdown(f"💸 **Donne** {t['montant']:.2f}€ à {t['a']}")
                                                if a_recevoir:
                                                    for t in a_recevoir:
                                                        st.markdown(f"💶 **Reçoit** {t['montant']:.2f}€ de {t['de']}")
                                                
                                                if not a_donner and not a_recevoir:
                                                    st.caption("Aucun mouvement à prévoir.")


                                                # Dans la boucle des participants (colonne 3) :
                                                transferts_perso = [t for t in transferts_finaux if t['de'] == p or t['a'] == p]

                                                if transferts_perso:
                                                    # On prépare un titre spécifique pour le PDF
                                                    titre_pdf = f"Bilan Remboursements : {p}"
                                                    
                                                    # Appel de la fonction (p est passé pour que le PDF sache qui est le sujet principal)
                                                    pdf_p = generer_pdf_tricount(titre_pdf, df_groupe, transferts_perso, 0, sujet=p)
                                                    st.download_button(
                                                        label=f"📄 PDF {p}",
                                                        data=bytes(pdf_p),
                                                        file_name=f"Note_{p}.pdf",
                                                        mime="application/pdf",
                                                        key=f"pdf_btn_{p}_{groupe_choisi}",
                                                        use_container_width=True
                                                    )

                                    # --- ACTION GLOBALE TOUT EN BAS ---
                                    pdf_global = generer_pdf_tricount(f"Global - {groupe_choisi}", df_groupe, transferts_finaux, df_groupe['montant'].sum())
                                    st.download_button(
                                        label="📥 TÉLÉCHARGER LE BILAN COMPLET DU groupe (PDF)",
                                        data=bytes(pdf_global),
                                        file_name=f"Bilan_Global_{groupe_choisi}.pdf",
                                        mime="application/pdf",
                                        use_container_width=True
                                    )

                                else:
                                    st.success("✨ Tout le monde est parfaitement quitte !")


                        
                        # --- COLONNE 4 : HISTORIQUE ET MODIFICATIONS ---
                        with col_histo:
                            st.markdown("### 📜 Historique")
                            
                            if not df_tri.empty:
                                # Filtrage par groupe actuel ET exclusion de l'initialisation système
                                # On ne garde que les vraies dépenses (montant > 0 et pas payé par Système)
                                df_groupe_h = df_tri[
                                    (df_tri['groupe'] == groupe_choisi) & 
                                    (df_tri['payé_par'] != "Système") & 
                                    (df_tri['montant'] > 0)
                                ]
                                
                                if not df_groupe_h.empty:
                                    # --- CALCUL DU TOTAL ---
                                    total_groupe = df_groupe_h['montant'].sum()
                                    
                                    # Affichage du total
                                    st.metric(label=f"Total des dépenses : {groupe_choisi}", value=f"{total_groupe:.2f} €")

                                    # Liste des transactions (scrollable)
                                    with st.container(height=700):
                                        # Tri pour avoir les plus récentes en haut
                                        for idx, row in df_groupe_h.sort_index(ascending=False).iterrows():
                                            with st.container(border=True):
                                                c1, c2 = st.columns([3, 1])
                                                with c1:
                                                    st.markdown(f"**{row['libellé']}**")
                                                    # On convertit en datetime (au cas où c'est du texte) et on formate
                                                    date_formatee = pd.to_datetime(row['date']).strftime('%d/%m/%Y')
                                                    # On récupère l'émoji de la ligne, ou un emoji par défaut si la colonne est vide
                                                    emoji_p = row['emoji'] if 'emoji' in row and str(row['emoji']) != 'nan' else "👤"
                                                    # Affichage avec l'émoji associé
                                                    st.caption(f"📅 {date_formatee}  Par **{row['payé_par']}**{emoji_p}")
                                                    st.markdown(f"💰 **{row['montant']:.2f}€**")
                                                with c2:
                                                    if st.button("🗑️", key=f"del_{row['id']}"): # Utilise l'ID de la base
                                                        if supprimer_transaction_tricount_neon(row['id']): 
                                                            st.toast("✅ Transaction supprimée")
                                                            st.rerun()
                                                    
                                                    # Bouton édition
                                                    if st.button("✏️", key=f"edit_{row.get('id', idx)}"):
                                                        modifier_transaction(row) # On n'envoie plus que la ligne (row)
                                else:
                                    st.info("Aucune dépense enregistrée.")
                            else:
                                st.write("Le sheet est vide.")
        afficher_espace_tricount()