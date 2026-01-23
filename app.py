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
from fpdf import FPDF


st.set_page_config(page_title="Mes Budgets",page_icon="💰", layout="wide",initial_sidebar_state="collapsed")



# Création de la connexion
    # Test forcé (remplace la ligne 19 de ton app.py)
    # Ligne 20 corrigée :
# --- ÉTAPE A : CONNEXION ET CHARGEMENT DES UTILISATEURS ---
conn = st.connection("gsheets", type=GSheetsConnection)


# Définis ta version ici centralisée
APP_VERSION = "V1.2.3"

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
        pdf.cell(30, 8, "Date", border=1, fill=True)
        pdf.cell(70, 8, "Libelle", border=1, fill=True)
        pdf.cell(50, 8, "Paye par", border=1, fill=True)
        pdf.cell(40, 8, "Montant", border=1, fill=True, ln=True)

        for _, row in df_groupe.iterrows():
            if float(str(row['Montant']).replace(',', '.')) > 0:
                pdf.cell(30, 8, str(row['Date']), border=1)
                libelle_propre = str(row['Libellé'])[:35] 
                pdf.cell(70, 8, libelle_propre, border=1)
                pdf.cell(50, 8, str(row['Payé_Par']), border=1)
                pdf.cell(40, 8, f"{float(str(row['Montant']).replace(',', '.')):.2f} EUR", border=1, ln=True)
    
    return pdf.output()



def charger_tricount_gsheet(user_connecte):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(worksheet="Tricount")
    # FILTRE CRUCIAL : On ne garde que les lignes de l'utilisateur logué
    return df[df['Utilisateur'] == user_connecte]


def supprimer_transaction_tricount(df_source, index_a_supprimer, connection):
    try:
        # 1. On crée le nouveau DataFrame sans la ligne
        df_mis_a_jour = df_source.drop(index=index_a_supprimer)
        
        # 2. On utilise la connexion existante pour mettre à jour le Sheet
        # On précise l'onglet "Transactions" (à adapter selon ton cas)
        connection.update(worksheet="Tricount", data=df_mis_a_jour)
        
        return True
    except Exception as e:
        st.error(f"Erreur lors de la mise à jour : {e}")
        return False



def sauvegarder_transaction_tricount(df_actuel, nouvelle_ligne_dict):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # 1. Créer le nouveau DataFrame
        new_row_df = pd.DataFrame([nouvelle_ligne_dict])
        
        # 2. Fusionner avec l'existant
        if df_actuel is not None and not df_actuel.empty:
            df_final = pd.concat([df_actuel, new_row_df], ignore_index=True)
        else:
            df_final = new_row_df
            
        # 3. Mise à jour CRUCIALE
        # On utilise clear_cache=True pour forcer Streamlit à oublier l'ancienne version
        conn.update(worksheet="Tricount", data=df_final)
        
        # 4. Vider manuellement le cache de l'app pour plus de sécurité
        st.cache_data.clear() 
        
        return True
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return False


def charger_tricount_gsheet(username):
    try:
        # On utilise la connexion existante
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # On lit l'onglet "Tricount"
        # ttl=0 permet de forcer la lecture des données fraîches sans cache
        df = conn.read(worksheet="Tricount", ttl=0)
        
        if df is not None and not df.empty:
            # On s'assure que les colonnes sont bien nommées et on filtre par utilisateur
            df_user = df[df['Utilisateur'] == username].copy()
            return df_user
        
        # Si le tableau est vide, on retourne un DF avec les bonnes colonnes
        return pd.DataFrame(columns=["Date", "Libellé", "Payé_Par", "Pour_Qui", "Montant", "Utilisateur"])
    
    except Exception as e:
        # En cas d'erreur (ex: onglet inexistant), on retourne un DF vide structuré
        return pd.DataFrame(columns=["Date", "Libellé", "Payé_Par", "Pour_Qui", "Montant", "Utilisateur"])



def relancer_avec_succes(message="Action réussie !"):
    st.toast(message, icon="✅")
    time.sleep(0.8)
    st.rerun()


def sauvegarder_notes(texte, username):
    try:
        # 1. Lire l'onglet "Notes"
        # ttl=0 pour être sûr de ne pas lire une version en cache
        df_notes = conn.read(worksheet="Notes", ttl=0)
        
        # 2. Vérifier si l'utilisateur existe déjà dans cet onglet
        # On suppose que la colonne s'appelle 'Utilisateur'
        if username in df_notes['Utilisateur'].values:
            # Mise à jour de la note pour cet utilisateur
            df_notes.loc[df_notes['Utilisateur'] == username, 'Texte'] = texte
        else:
            # Si l'utilisateur n'existe pas encore dans l'onglet Notes, on l'ajoute
            nouvelle_ligne = pd.DataFrame({'Utilisateur': [username], 'Texte': [texte]})
            df_notes = pd.concat([df_notes, nouvelle_ligne], ignore_index=True)
            
        # 3. Renvoi du DataFrame complet vers le Sheet
        conn.update(worksheet="Notes", data=df_notes)
        return True
    except Exception as e:
        st.error(f"Erreur de sauvegarde dans l'onglet Notes : {e}")
        return False

def charger_notes(username):
    try:
        df_notes = conn.read(worksheet="Notes", ttl=0)
        # On récupère la valeur de la colonne 'Texte' pour l'utilisateur
        note = df_notes.loc[df_notes['Utilisateur'] == username, 'Texte'].values[0]
        return note if (isinstance(note, str) and note != "nan") else ""
    except:
        return ""
    

def charger_budgets_complets(username, mois, compte):
    """Charge tous les budgets pour pré-remplir l'interface."""
    try:
        df_all = conn.read(worksheet="Budgets", ttl=0)
        mask = (df_all['username'] == username) & (df_all['Mois'] == mois) & (df_all['Compte'] == compte)
        return df_all[mask]
    except:
        return pd.DataFrame(columns=['username', 'Mois', 'Compte', 'Type', 'Nom', 'Somme'])

def enregistrer_ligne_budget(username, mois, compte, categorie, montant):
    """Remplace sauvegarder_objectifs pour une gestion ligne par ligne."""
    try:
        # 1. Lecture
        try:
            df_all = conn.read(worksheet="Budgets", ttl=0).copy()
        except:
            df_all = pd.DataFrame(columns=['username', 'Mois', 'Compte', 'Type', 'Nom', 'Somme'])

        # 2. On retire l'ancienne valeur pour cette catégorie précise
        mask_existant = (
            (df_all['username'].astype(str) == str(username)) & 
            (df_all['Mois'].astype(str) == str(mois)) & 
            (df_all['Compte'].astype(str) == str(compte)) & 
            (df_all['Nom'].astype(str) == str(categorie))
        )
        df_final = df_all[~mask_existant]

        # 3. Ajout de la nouvelle ligne si montant > 0
        if montant > 0:
            nouvelle_ligne = pd.DataFrame([{
                'username': username, 'Mois': mois, 'Compte': compte,
                'Type': 'Categorie', 'Nom': categorie, 'Somme': montant
            }])
            df_final = pd.concat([df_final, nouvelle_ligne], ignore_index=True)

        # 4. Écriture GSheets
        conn.update(worksheet="Budgets", data=df_final)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erreur : {e}")
        return False



def trouver_categorie_similaire(nom_transaction, df_historique, seuil=0.6):
    """
    Cherche une transaction similaire dans l'historique et renvoie sa catégorie.
    seuil : 0.6 signifie 60% de ressemblance (ajustable).
    """
    if df_historique.empty:
        return None
    
    # On récupère tous les noms de transactions uniques déjà catégorisées
    noms_connus = df_historique['Nom'].unique().tolist()
    
    # On cherche les correspondances proches
    matches = get_close_matches(nom_transaction, noms_connus, n=1, cutoff=seuil)
    
    if matches:
        nom_proche = matches[0]
        # On récupère la catégorie associée à ce nom proche
        categorie_suggeree = df_historique[df_historique['Nom'] == nom_proche]['Categorie'].iloc[0]
        return categorie_suggeree, nom_proche
    
    return None, None

def load_config_from_gsheets():
    try:
        df_users = conn.read(worksheet="Users", ttl=0)
        credentials = {'usernames': {}}
        for _, row in df_users.iterrows():
            credentials['usernames'][row['username']] = {
                'name': row['name'],
                'password': row['password'],
                'email': row.get('email', '') 
            }
        return credentials
    except Exception:
        return {'usernames': {}}

# On prépare l'authentificateur
credentials_data = load_config_from_gsheets()

config = {
    'credentials': credentials_data,
    'cookie': {
        'expiry_days': 30, 
        'key': 'signature_unique',  
        'name': 'auth_cookie_v2'
    }
}

# CORRECTION : On ne passe QUE 4 arguments maintenant
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)




@st.cache_data(ttl=1800)
def charger_config(username):
    try:
        df_cfg = conn.read(worksheet="Configuration", ttl=0)
        
        # Filtre par utilisateur (insensible à la casse)
        if "User" in df_cfg.columns:
            df_cfg = df_cfg[df_cfg["User"].astype(str).str.lower() == username.lower()].copy()
        
        config_dict = {}
        for _, row in df_cfg.iterrows():
            nom_compte = str(row["Compte"]).strip()
            
            config_dict[nom_compte] = {
                "Solde": float(row.get("Solde", 0)),
                "Groupe": str(row.get("Groupe", "Personnel")),
                "Objectif": float(row.get("Objectif", 0)), # Ajout de l'objectif
                "Couleur": str(row.get("Couleur", "#3498db"))
            }
        return config_dict
    except Exception as e:
        return {}


@st.cache_data(ttl=1800)
def charger_donnees(username):
        try:
            df = conn.read(worksheet="Transactions", ttl=0)
            
            if df.empty:
                return pd.DataFrame()

            # Nettoyage des noms de colonnes (enlève les espaces invisibles)
            df.columns = [c.strip() for c in df.columns]

            if "User" in df.columns:
                # FILTRE : On compare en minuscules pour éviter les erreurs Suzanne / suzanne
                df = df[df["User"].astype(str).str.strip().str.lower() == str(username).strip().lower()].copy()
            else:
                st.error("⚠️ La colonne 'User' est introuvable dans l'onglet Transactions !")
                return pd.DataFrame()

            
            return df
        except Exception as e:
            st.error(f"Erreur : {e}")
            return pd.DataFrame()




def sauvegarder_groupes(nouveaux_groupes_dict, username):
    """
    Met à jour la colonne 'Groupe' pour chaque compte de l'utilisateur.
    Structure attendue : Compte, Groupe, Objectif, Solde, User, Couleur
    """
    try:
        # 1. Lire TOUTE la feuille actuelle
        df_global = conn.read(worksheet="Configuration", ttl=0)
        
        # 2. Isoler les données des AUTRES (Utilisation de l'argument username pour plus de sécurité)
        df_autres = df_global[df_global["User"] != username]
        
        # 3. Récupérer les données actuelles de MOI pour ne pas perdre 'Objectif' ou 'Solde'
        df_moi = df_global[df_global["User"] == username].copy()
        
        # 4. Appliquer les nouveaux groupes
        # On part du principe que nouveaux_groupes_dict est { "NomDuGroupe": ["Compte1", "Compte2"] }
        for grp, comptes in nouveaux_groupes_dict.items():
            for c in comptes:
                # Nettoyage des espaces pour être sûr que la correspondance se fasse
                mask = (df_moi["Compte"].astype(str).str.strip() == str(c).strip())
                if mask.any():
                    df_moi.loc[mask, "Groupe"] = grp
        
        # 5. Fusionner et sauvegarder
        df_final = pd.concat([df_autres, df_moi], ignore_index=True)
        conn.update(worksheet="Configuration", data=df_final)
        
        # 6. Actualisation
        st.cache_data.clear() # On vide le cache pour actualiser l'affichage
        st.success("✅ Groupes sauvegardés !")
        
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde : {e}")

def clear_input_new_cat():
    st.session_state.input_new_cat = ""

def afficher_ligne_compacte(row, couleur_montant, prefixe=""):
    # 1. Sécurité pour la Date (Évite l'erreur NaTType)
    if pd.isnull(row['Date']):
        date_str = "??/??"
    else:
        try:
            # Si c'est déjà un objet datetime
            date_str = row['Date'].strftime('%d/%m')
        except AttributeError:
            # Si c'est du texte, on essaie de convertir ou on prend les 5 premiers caractères
            date_str = str(row['Date'])[:5]

    # 2. Préparation des données texte
    cat = str(row['Categorie']) if pd.notna(row['Categorie']) else "À catégoriser ❓"
    ico = cat[:1] if cat else "💰"
    
    if any(x in cat for x in ["Virement :", "Transfert Interne"]) and "🤝" not in cat:
        ico = "🔄"
    
    # 3. Sécurité pour le texte (Nom et Compte)
    nom_propre = str(row['Nom']).replace('"', "&quot;") if pd.notna(row['Nom']) else "Sans nom"
    compte_str = str(row['Compte']) if pd.notna(row['Compte']) else "Inconnu"
    
    # 4. Sécurité pour le montant
    try:
        valeur_montant = abs(float(row['Montant']))
        montant_str = f"{prefixe}{valeur_montant:.2f}€"
    except (ValueError, TypeError):
        montant_str = "0.00€"

    # Ici, tu peux continuer avec tes st.columns() pour l'affichage...

    # IMPORTANT : Le HTML commence collé à gauche dans la chaîne pour éviter l'interprétation "code"
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
    

def sauvegarder_config(config_dict, username):
    try:
        # 1. Préparer les données de l'utilisateur actuel
        # orient='index' transforme ton dictionnaire {Compte: {Solde, Groupe...}} en lignes
        df_user = pd.DataFrame.from_dict(config_dict, orient='index').reset_index()
        df_user.rename(columns={'index': 'Compte'}, inplace=True)
        
        # On s'assure que la colonne User est bien remplie
        df_user["User"] = username 
        
        # 2. Lire TOUTE la config pour préserver les autres utilisateurs
        df_global = conn.read(worksheet="Configuration", ttl=0)
        
        # 3. Fusionner : on garde les autres, et on ajoute les nouvelles données de l'utilisateur
        if not df_global.empty and "User" in df_global.columns:
            # On exclut l'utilisateur actuel de la base globale avant de rajouter sa nouvelle config
            df_autres = df_global[df_global["User"].astype(str).str.lower() != username.lower()]
            df_final = pd.concat([df_autres, df_user], ignore_index=True)
        else:
            # Si la feuille est vide ou mal formatée
            df_final = df_user
            
        # 4. Envoi vers GSheets et nettoyage du cache
        conn.update(worksheet="Configuration", data=df_final)
        st.cache_data.clear()
        
    except Exception as e:
        st.error(f"Erreur sauvegarde config : {e}")



def update_couleur_compte(nom_compte, username):
    # 1. On identifie le widget qui vient d'être cliqué
    cle_picker_actuel = f"cp_{nom_compte}"
    
    if cle_picker_actuel in st.session_state:
        # 2. On met à jour le dictionnaire config_groupes avec TOUTES les couleurs
        # présentes dans le session_state (pour éviter le retour au bleu des autres)
        if "config_groupes" in st.session_state:
            for c in st.session_state.config_groupes:
                cle_p = f"cp_{c}"
                if cle_p in st.session_state:
                    # On prend la couleur en direct du widget
                    st.session_state.config_groupes[c]["Couleur"] = st.session_state[cle_p]
                elif "Couleur" not in st.session_state.config_groupes[c]:
                    # Sécurité si le widget n'existe pas encore
                    st.session_state.config_groupes[c]["Couleur"] = "#1f77b4"

            # 3. On sauvegarde le dictionnaire complet (en passant le username)
            sauvegarder_config(st.session_state.config_groupes, username)



# --- 5. DESIGN (SORTI DU IF POUR TOUJOURS S'APPLIQUER) ---
st.markdown("""
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 0rem; }
        header[data-testid="stHeader"] { background: rgba(0,0,0,0); }
    </style>
""", unsafe_allow_html=True)

# --- 2. DICTIONNAIRES ET CONSTANTES ---
CORRESPONDANCE = {
    "Date": ["Date", "Date opération", "Date de valeur", "Effective Date", "Date op", "Date val", "Le", "Date de comptabilisation","Date operation", "date"],
    "Nom": ["Nom", "Libelle simplifie", "Libellé", "Description", "Transaction", "Libellé de l'opération", "Détails", "Objet", "Type"],
    "Montant": ["Montant", "Montant(EUROS)", "Valeur", "Amount", "Prix", "Montant net", "Somme"],
    "Debit": ["Debit", "Débit"],
    "Credit": ["Credit", "Crédit"]
}

NOMS_MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

@st.cache_data(ttl=1800)
def charger_categories_perso():
    defaut = [
        "💰 Salaire", "🏥 Remboursements", "🤝 Virements Reçus", "👫 Compte Commun",
        "📱 Abonnements", "🛒 Alimentation", "🛍️ Shopping", "👕 Habillement", 
        "⚖️ Impôts", "🏦 Frais Bancaires", "🏠 Assurance Habitation", "🎮 Jeux vidéos",
        "🩺 Mutuelle", "💊 Pharmacie", "👨‍⚕️ Médecin/Santé", "🔑 Loyer", 
        "🔨 Bricolage", "🚌 Transports", "⛽ Carburant", "🚗 Auto", 
        "💸 Virements Perso", "🏧 Retraits", "🌐 Web/Énergie", "🔄 Virement : Livret A vers CCP", "🔄 Virement : CCP vers Livret A","❓ Autre"
    ]
    try:
        df_cat = conn.read(worksheet="Categories", ttl=0)
        # FILTRAGE PAR USER
        perso = df_cat[df_cat["User"] == st.session_state["username"]]["Nom"].tolist()
        return sorted(list(set(defaut + perso)))
    except:
        return sorted(defaut)

def sauvegarder_nouvelle_categorie(nouvelle_cat, username):
    """
    Ajoute une nouvelle catégorie personnalisée pour l'utilisateur.
    """
    try:
        # 1. Lire les catégories existantes
        df_cat = conn.read(worksheet="Categories", ttl=0)
        
        # 2. Vérification des doublons pour cet utilisateur précis
        if not df_cat.empty:
            doublon = df_cat[(df_cat["Nom"] == nouvelle_cat) & (df_cat["User"] == username)]
            if not doublon.empty:
                st.warning(f"La catégorie '{nouvelle_cat}' existe déjà.")
                return False

        # 3. Préparer la nouvelle ligne
        new_row = pd.DataFrame({"Nom": [nouvelle_cat], "User": [username]})
        
        # 4. Fusionner et sauvegarder
        df_final = pd.concat([df_cat, new_row], ignore_index=True)
        conn.update(worksheet="Categories", data=df_final)
        
        # 5. Nettoyage du cache pour actualiser les listes déroulantes
        st.cache_data.clear()
        return True
        
    except Exception as e:
        st.error(f"Erreur lors de l'ajout de la catégorie : {e}")
        return False


LISTE_CATEGORIES_COMPLETE = charger_categories_perso()

# --- 3. TOUTES LES FONCTIONS ---


@st.cache_data(ttl=1800)
def charger_memoire(username):
    try:
        df_memo = conn.read(worksheet="Memoire", ttl=0)
        if df_memo.empty: return {}
        
        # Filtre par utilisateur
        if "User" in df_memo.columns:
            df_memo = df_memo[df_memo["User"] == username]
            
        return df_memo.set_index('Nom')['Categorie'].to_dict()
    except:
        return {}

def sauvegarder_apprentissage(nom_ope, categorie, username):
    """
    Mémorise la catégorie associée à un libellé simplifié pour un utilisateur précis.
    """
    try:
        # 1. Charger la mémoire existante de l'utilisateur
        memoire = charger_memoire(username)
        
        # 2. Simplifier le nom et mettre à jour le dictionnaire local
        nom_clean = simplifier_nom_definitif(nom_ope)
        memoire[nom_clean] = categorie
        
        # 3. Convertir le dictionnaire mis à jour en DataFrame pour cet utilisateur
        df_user_memo = pd.DataFrame(list(memoire.items()), columns=['Nom', 'Categorie'])
        df_user_memo["User"] = username
        
        # 4. Lire TOUTE la mémoire globale pour préserver les autres utilisateurs
        df_global = conn.read(worksheet="Memoire", ttl=0)
        
        # 5. Fusionner : on garde les autres et on ajoute les nouvelles règles de l'utilisateur
        if not df_global.empty and "User" in df_global.columns:
            df_autres = df_global[df_global["User"] != username]
            df_final = pd.concat([df_autres, df_user_memo], ignore_index=True)
        else:
            df_final = df_user_memo
            
        # 6. Mise à jour GSheets et vidage du cache
        conn.update(worksheet="Memoire", data=df_final)
        st.cache_data.clear()
        
    except Exception as e:
        st.error(f"Erreur lors de l'apprentissage : {e}")

@st.cache_data(ttl=1800)
def charger_tout_le_theme(username): # Ajoutez username ici
    try:
        df_theme = conn.read(worksheet="Theme", ttl="0")
        if df_theme.empty: return {}
        
        # FILTRE CRUCIAL : On ne prend que les lignes de l'utilisateur
        df_user = df_theme[df_theme["User"] == username]
        
        return df_user.set_index("Element")["Couleur"].to_dict()
    except Exception:
        return {}

    # Au début de votre script, après l'authentification réussie :
if "user_theme" not in st.session_state:
    try:
        df_theme = conn.read(worksheet="Theme", ttl=300) # Cache de 5 min pour le design
        st.session_state.user_theme = df_theme[df_theme["User"] == st.session_state["username"]]
    except:
        st.session_state.user_theme = pd.DataFrame()

@st.cache_data(ttl=1800)
# Nouvelle fonction charger_couleur qui ne lit plus GSheets mais la session :
def charger_couleur(type_couleur="Couleur", default="#222222"):
    try:
        # On utilise la fonction qui a le cache @st.cache_data
        theme_dict = charger_tout_le_theme(st.session_state["username"])
        
        # On récupère la couleur dans le dictionnaire en mémoire (0 requête API)
        return theme_dict.get(type_couleur, default)
    except:
        return default

def sauvegarder_plusieurs_couleurs(nouveaux_reglages):
    try:
        df_actuel = conn.read(worksheet="Theme", ttl="0")
        # On crée le DF des nouveaux réglages pour CET utilisateur
        data_user = []
        for element, hex_color in nouveaux_reglages.items():
            data_user.append({"Element": element, "Couleur": hex_color, "User": st.session_state["username"]})
        df_user = pd.DataFrame(data_user)

        # On filtre pour garder les thèmes des autres
        if not df_actuel.empty and "User" in df_actuel.columns:
            df_autres = df_actuel[df_actuel["User"] != st.session_state["username"]]
            df_final = pd.concat([df_autres, df_user], ignore_index=True)
        else:
            df_final = df_user

        conn.update(worksheet="Theme", data=df_final)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erreur thème : {e}")
        return False


@st.cache_data(ttl=1800)
def charger_groupes(username): # <--- Ajout du paramètre username
    try:
        # On passe le username à charger_config pour qu'il filtre les bonnes données
        config = charger_config(username) 
        
        if config:
            # On extrait les groupes uniques (en gardant la logique de repli sur "Personnel")
            groupes = list(set(v.get("Groupe", "Personnel") for v in config.values()))
            # On retourne la liste triée en ignorant les valeurs vides
            return sorted([g for g in groupes if g])
        
        return ["Personnel"]
    except Exception as e:
        # Optionnel : st.error(f"Erreur charger_groupes: {e}") 
        return ["Personnel"]
    
    







def clean_montant_physique(valeur):
    if pd.isna(valeur) or valeur == "": return 0.0
    s = str(valeur).replace('\xa0', '').replace(' ', '').replace('€', '').replace('$', '')
    if ',' in s and '.' in s: s = s.replace(',', '')
    elif ',' in s: s = s.replace(',', '.')
    try: return float(s)
    except: return 0.0







def sauvegarder_donnees(nouveau_df, username=None):
    try:
        # 1. Lecture du fichier
        df_global = conn.read(worksheet="Transactions", ttl=0)
        user_actif = st.session_state.get("username", username)

        # 2. Assignation du user
        nouveau_df["User"] = user_actif
        
        # 3. Filtrage des données des autres
        if not df_global.empty and "User" in df_global.columns:
            df_global["User"] = df_global["User"].astype(str).str.strip()
            df_autres = df_global[df_global["User"].str.lower() != user_actif.lower()].copy()
        else:
            df_autres = df_global

        # 4. Concaténation
        df_final = pd.concat([df_autres, nouveau_df], ignore_index=True)
        
        # --- 5. CORRECTION DU FORMATAGE DE LA DATE ---
        # On force Pandas à comprendre que le jour est en premier (dayfirst=True)
        # On utilise 'mixed' pour gérer les formats qui pourraient varier (texte vs datetime)
        df_final['Date'] = pd.to_datetime(df_final['Date'], dayfirst=True, errors='coerce')
        
        # On transforme en texte formaté JJ/MM/AAAA pour Google Sheets
        df_final['Date'] = df_final['Date'].dt.strftime('%d/%m/%Y')

        # 6. Mise à jour vers Google Sheets
        conn.update(worksheet="Transactions", data=df_final)
        
        # 7. Nettoyage du cache
        st.cache_data.clear()
        
    except Exception as e:
        st.error(f"Erreur de sauvegarde : {e}")



@st.cache_data(ttl=1800)
def charger_previsions():
    try:
        df = conn.read(worksheet="Previsions", ttl="0")
        if df.empty:
            return pd.DataFrame(columns=["Date", "Nom", "Montant", "Categorie", "Compte", "Mois", "Année", "User"])
        
        # FILTRAGE PAR USER
        if "User" in df.columns:
            df = df[df["User"] == st.session_state["username"]].copy()
            
        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
        df["Montant"] = pd.to_numeric(df["Montant"], errors='coerce').fillna(0.0)
        return df
    except Exception:
        return pd.DataFrame(columns=["Date", "Nom", "Montant", "Categorie", "Compte", "Mois", "Année", "User"])

def sauvegarder_previsions(df_prev, username):
    """
    Sauvegarde les prévisions budgétaires sur GSheets en isolant l'utilisateur.
    """
    try:
        # 1. On s'assure que toutes les lignes du DF envoyé ont bien le nom du User
        df_prev["User"] = username
        
        # 2. On récupère la base globale pour fusionner sans écraser les autres
        df_global = conn.read(worksheet="Previsions", ttl=0)
        
        # 3. Isolation des données des autres
        if not df_global.empty and "User" in df_global.columns:
            df_autres = df_global[df_global["User"].astype(str).str.lower() != username.lower()]
            # 4. Concaténation (Données des autres + Mes prévisions)
            df_final = pd.concat([df_autres, df_prev], ignore_index=True)
        else:
            # Si le fichier est vide ou n'a pas encore de colonne User
            df_final = df_prev
        
        # 5. Envoi vers GSheets et nettoyage du cache
        conn.update(worksheet="Previsions", data=df_final)
        st.cache_data.clear()
        
    except Exception as e:
        st.error(f"❌ Erreur de sauvegarde Cloud : {e}")



def simplifier_nom_definitif(nom):
    if not isinstance(nom, str): return str(nom)
    nom = nom.upper()
    nom = re.sub(r'(FAC|REF|NUM|ID|PRLV|VIREMENT)\s*[:.\-]?\s*[0-9A-Z]+', '', nom)
    nom = re.sub(r'\d{2}[\./]\d{2}([\./]\d{2,4})?', '', nom)
    for m in ["ACHAT CB", "ACHAT", "CB", "CARTE", "VERSEMENT", "CHEQUE", "SEPA"]: nom = nom.replace(m, "")
    return ' '.join(re.sub(r'[\*\-\/#]', ' ', nom).split()).strip() or "AUTRE"

def categoriser(nom_operation, montant=0, compte_actuel=None, ligne_complete=None):
    n_brut = str(nom_operation).upper()
    n_clean = simplifier_nom_definitif(n_brut)
    
    # 1. MÉMOIRE (Priorité absolue)
    # 1. MÉMOIRE (Priorité absolue)
    # CORRECT :
    memoire = charger_memoire(st.session_state["username"])
    if n_clean in memoire: return memoire[n_clean]

    # 2. SCAN COMPLET DE LA LIGNE
    if ligne_complete is not None:
        # On fusionne Libellé + Infos complémentaires (colonne 5) [cite: 1, 2]
        texte_integral = n_brut + " " + str(ligne_complete.get('Informations complementaires', '')).upper()
    else:
        texte_integral = n_brut

    # 3. LES COMPTES ET PROCHES
    mes_comptes = ["LIVRET A", "LDDS", "COMPTE CHEQUES", "COMMUN"]
    proches = ["MARYLINE FONTA", "AURORE FONTA", "LEBARBIER THEO", "LEBARBIER DIDIER"]

    # --- ÉTAPE A : DÉTECTION DES TRANSFERTS INTERNES (🔄) ---
    # On cherche le mot "VERS" suivi d'un de tes comptes [cite: 2, 5]
    
    if "VERS" in texte_integral:
        if "LIVRET A" in texte_integral: return "🔄 Virement : CCP vers Livret A"
        if "COMPTE CHEQUES" in texte_integral or "CCP" in texte_integral: return "🔄 Virement : Livret A vers CCP"
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
    CATEGORIES_MOTS_CLES = {
        "💰 Salaire": ["MELTED", "JEFF DB", "FRANCE TRAVAIL", "POLE EMPLOI", "SARL", "JEFF DE BRUGES"],
        "🏥 Remboursements": ["NOSTRUMCARE", "AMELI", "CPAM", "REMBOURSEMENT", "SANTÉ", "FAUSTINE BOJUC"],
        "👫 Compte Commun": ["A FONTA AUDE OU LEBARBIER THEO", "AUDE FONTATHEO LEBARBIE", "VERSEMENT COMMUN", "VIREMENT COMMUN"],
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
    
    for cat, mots in CATEGORIES_MOTS_CLES.items():
        if any(m in n_brut for m in mots):
            return cat
    
    return "💰 Autres Revenus" if montant > 0 else "❓ Autre"

def mettre_a_jour_soldes(df_transactions, soldes_initiaux):
    # On harmonise tout en MAJUSCULES et sans espaces pour le calcul
    nouveaux_soldes = {str(k).strip().upper(): float(v) for k, v in soldes_initiaux.items()}
    config = st.session_state.get('config_groupes', {})

    for _, ligne in df_transactions.iterrows():
        montant = float(ligne['Montant'])
        compte_source = str(ligne['Compte']).strip().upper()
        cat = str(ligne['Categorie']).upper()

        # IMPACT SUR LE COMPTE QUI A LA LIGNE (CCP par exemple)
        if compte_source in nouveaux_soldes:
            nouveaux_soldes[compte_source] += montant
        
        # LOGIQUE DE TRANSFERT (Livret A par exemple)
        if "🔄" in cat:
            # On cherche le groupe du compte source
            # On scanne la config pour trouver le compte source (peu importe la casse)
            nom_source_config = next((k for k in config.keys() if k.strip().upper() == compte_source), None)
            
            if nom_source_config:
                groupe_source = config[nom_source_config].get("Groupe")
                
                for nom_c, cfg in config.items():
                    nom_c_upper = str(nom_c).strip().upper()
                    
                    # Si même groupe, compte différent, et mot clé présent
                    if cfg.get("Groupe") == groupe_source and nom_c_upper != compte_source:
                        # On prend le premier mot (ex: "LIVRET")
                        mots = [m for m in nom_c_upper.split() if len(m) > 2]
                        if mots and mots[0] in cat:
                            if nom_c_upper in nouveaux_soldes:
                                if montant < 0: # Argent qui sort du CCP
                                    nouveaux_soldes[nom_c_upper] += abs(montant)
                                else: # Argent qui rentre sur le CCP (depuis Livret)
                                    nouveaux_soldes[nom_c_upper] -= abs(montant)
                                break
    return nouveaux_soldes


def actualiser_donnees():
    # 1. On vide le cache de toutes les fonctions décorées avec @st.cache_data
    st.cache_data.clear()
    
    # 2. On supprime les données stockées dans la session pour forcer le rechargement
    if "df" in st.session_state:
        del st.session_state.df
    if "df_prev" in st.session_state:
        del st.session_state.df_prev
    if "config_groupes" in st.session_state:
        del st.session_state.config_groupes
        
    st.success("Données actualisées depuis Google Sheets !")
    # 3. On relance l'app
    relancer_avec_succes()






# --- 2. LOGIQUE D'AFFICHAGE (CONNEXION / INSCRIPTION) ---
if not st.session_state.get("authentication_status"):
    # On crée les onglets
    tabs = st.tabs(["🔐 Connexion", "👤 Créer un compte", "🔑 Reset Mot de passe"])
    
    with tabs[0]:
        try:
            # 1. On tente le login
            authenticator.login(location='main')
        except Exception as e:
            st.error(f"Erreur technique : {e}")
        
        # 2. LA CORRECTION : Si le statut vient de passer à True, on force le rafraîchissement
        # Cela évite de devoir cliquer une deuxième fois pour voir l'app
        if st.session_state.get("authentication_status"):
            relancer_avec_succes()

        # 3. Gestion des messages d'erreur (inchangée)
        if st.session_state.get("authentication_status") is False:
            st.error('Utilisateur ou mot de passe incorrect')
        elif st.session_state.get("authentication_status") is None:
            st.info("Veuillez entrer vos identifiants.")
            
    with tabs[1]:
        # --- FORMULAIRE D'INSCRIPTION ---
        with st.form("formulaire_inscription"):
            nouveau_user = st.text_input("Identifiant (Username)")
            nouveau_nom = st.text_input("Nom complet")
            nouveau_email = st.text_input("Email (Indispensable pour la récupération)")
            nouveau_pass = st.text_input("Mot de passe", type="password")
            
            bouton_creer = st.form_submit_button("Créer mon compte")
            
            if bouton_creer:
                if nouveau_user and nouveau_pass and nouveau_email:
                    try:
                        df_actuel = conn.read(worksheet="Users", ttl=0)
                        
                        # Vérification de l'existence
                        if not df_actuel.empty and nouveau_user in df_actuel['username'].values:
                            st.error("Cet identifiant existe déjà.")
                        else:
                            hash_pass = stauth.Hasher.hash(nouveau_pass)
                            
                            nouvelle_ligne = pd.DataFrame([{
                                'username': nouveau_user,
                                'name': nouveau_nom,
                                'password': hash_pass,
                                'email': nouveau_email
                            }])
                            
                            df_final = pd.concat([df_actuel, nouvelle_ligne], ignore_index=True)
                            conn.update(worksheet="Users", data=df_final)
                            
                            st.success(f"✅ Compte '{nouveau_user}' créé avec succès !")
                            st.cache_data.clear()
                            time.sleep(2)
                            relancer_avec_succes()
                    except Exception as e:
                        st.error(f"Erreur lors de la sauvegarde : {e}")
                else:
                    st.warning("Veuillez remplir tous les champs (Identifiant, Email et Mot de passe).")
    
    with tabs[2]:
        st.write("Veuillez remplir les informations suivantes pour réinitialiser votre accès.")
            
        with st.form("form_forgot_custom"):
            user_to_reset = st.text_input("Votre Identifiant (Username)").strip().lower()
            email_to_verify = st.text_input("Votre Email enregistré").strip().lower()
            new_pass_1 = st.text_input("Nouveau mot de passe", type="password")
            new_pass_2 = st.text_input("Confirmez le nouveau mot de passe", type="password")
            
            submit_reset = st.form_submit_button("Réinitialiser mon mot de passe")

            if submit_reset:
                if not user_to_reset or not email_to_verify or not new_pass_1:
                    st.warning("Veuillez remplir tous les champs.")
                elif new_pass_1 != new_pass_2:
                    st.error("Les deux mots de passe ne correspondent pas.")
                else:
                    # 1. Lecture de la base Users
                    df_users = conn.read(worksheet="Users", ttl=0)
                    
                    # 2. Vérification de l'utilisateur et de l'email
                    # On prépare les données pour la comparaison (minuscules et sans espaces)
                    df_users['user_check'] = df_users['username'].astype(str).str.strip().str.lower()
                    df_users['email_check'] = df_users['email'].astype(str).str.strip().str.lower()
                    
                    # On cherche si la combinaison User + Email existe
                    match = df_users[(df_users['user_check'] == user_to_reset) & 
                                    (df_users['email_check'] == email_to_verify)]
                    
                    if not match.empty:
                        # 3. On génère le nouveau Hash
                        hash_nouveau = stauth.Hasher.hash(new_pass_1)
                        
                        # 4. On met à jour la ligne originale dans le DataFrame
                        index_to_update = match.index[0]
                        df_users.at[index_to_update, 'password'] = hash_nouveau
                        
                        # 5. On nettoie les colonnes de test et on sauvegarde vers GSheets
                        df_users = df_users.drop(columns=['user_check', 'email_check'])
                        conn.update(worksheet="Users", data=df_users)
                        
                        st.success(f"✅ Succès ! Le mot de passe de '{user_to_reset}' a été mis à jour.")
                        st.info("Vous pouvez maintenant vous connecter en haut de la page.")
                        st.balloons()
                        st.cache_data.clear()
                    else:
                        st.error("❌ L'identifiant ou l'email est incorrect. Vérifiez vos informations dans Google Sheets.")



# Si l'utilisateur EST connecté
else:
    # 1. Détection de changement d'utilisateur
    current_user = st.session_state.get("username")
    
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
        st.markdown(f"### 👤 {st.session_state.get('name', 'Utilisateur')}")
        
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
        user_actuel = st.session_state.get("username")
        
        if user_actuel:
            # 1. Chargement des données si elles n'existent pas encore en session
            if 'df' not in st.session_state or st.session_state.df is None:
                st.session_state.df = charger_donnees(user_actuel)
            
            if 'config_groupes' not in st.session_state:
                st.session_state.config_groupes = charger_config(user_actuel)
                
            if 'memoire' not in st.session_state:
                st.session_state.memoire = charger_memoire(user_actuel)

            # 2. Initialisation de la liste des groupes
            if 'groupes_liste' not in st.session_state:
                if st.session_state.config_groupes:
                    st.session_state.groupes_liste = sorted(list(set(
                        v.get("Groupe", "Personnel") for v in st.session_state.config_groupes.values()
                    )))
                else:
                    st.session_state.groupes_liste = ["Personnel"]
            
                        # Initialisation globale dans st.session_state
            if 'LISTE_CATEGORIES_COMPLETE' not in st.session_state:
                # On initialise avec une liste vide ou vos données de base
                st.session_state.LISTE_CATEGORIES_COMPLETE = []
            
            if "bloc_notes_content" not in st.session_state:
                # On va chercher la note enregistrée dans le Google Sheet
                # (Supposons que vous ayez une fonction charger_notes())
                st.session_state.bloc_notes_content = charger_notes(st.session_state.username)
            
            if "dernier_import_stats" not in st.session_state:
                st.session_state.dernier_import_stats = None
            

            # 3. Détection et fusion des comptes
            # On regarde les comptes dans le DF (filtré par user) et dans la config (filtrée par user)
            comptes_avec_data = st.session_state.df["Compte"].unique().tolist() if not st.session_state.df.empty else []
            comptes_configures = list(st.session_state.config_groupes.keys())
            
            # Fusion sans doublons
            comptes_detectes = sorted(list(set(comptes_avec_data + comptes_configures)))
            
            # 4. Attribution de couleurs par défaut pour les comptes non configurés
            for c in comptes_detectes:
                if c not in st.session_state.config_groupes:
                    st.session_state.config_groupes[c] = {
                        "Couleur": "#1f77b4", 
                        "Groupe": "Personnel", 
                        "Solde": 0.0
                    }

    # Récupération de la couleur de fond (vos préférences sauvegardées)
    bg_color_saved = st.session_state.get('page_bg_color', "#0e1117")

    df_h = st.session_state.df.copy()
   

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
        col_Icones = st.color_picker("Icones menus", charger_couleur("color_icones", "#15C98D"))
        bg_color = st.color_picker("Couleur de fond", charger_couleur("color_background", "#012523"))
        c_primary = st.color_picker("Couleur Primaire", charger_couleur("color_primary", "#2ecc71"))
        c_bg_sec = st.color_picker("Fond Secondaire", charger_couleur("color_bg_sec", "#013a36"))



        # --- 2. COULEURS DES COMPTES (MODIFIÉ POUR PERSISTANCE) ---
        st.subheader("🏦 Couleurs des comptes")
        
        comptes_actifs = []
        if not st.session_state.df.empty:
            comptes_actifs = st.session_state.df["Compte"].unique().tolist()
            
        tous_les_comptes = sorted(list(set(list(st.session_state.config_groupes.keys()) + comptes_actifs)))

        for c in tous_les_comptes:
            if c not in st.session_state.config_groupes:
                st.session_state.config_groupes[c] = {"Couleur": "#1f77b4", "Groupe": "Personnel", "Solde": 0.0}
            
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
                
                if sauvegarder_plusieurs_couleurs(batch_couleurs):
                    # Les couleurs de comptes sont déjà dans st.session_state.config_groupes
                    sauvegarder_config(st.session_state.config_groupes, st.session_state["username"])
                    st.success("Configuration sauvegardée !")
                    time.sleep(1)
                    relancer_avec_succes()

        
        if st.button("🔄 Actualiser les données", width='stretch'):
            actualiser_donnees()

    # 1. Toujours initialiser la session en haut de ton script
    if 'menu_option' not in st.session_state:
        st.session_state.menu_option = 0

    # 2. Le menu doit être défini SANS indentation (tout à gauche)
    # Pour qu'il soit créé à chaque rechargement
    selected = option_menu(
        menu_title=None,
        options=["Analyses", "Prévisionnel", "Gérer", "Importer", "Comptes", "Tricount"],
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
    index_actuel = ["Analyses", "Prévisionnel", "Gérer", "Importer", "Comptes","Tricount"].index(selected)
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
            # --- PRÉPARATION DES DONNÉES ---
            if st.session_state.df.empty:
                # On crée un faux DF vide pour éviter les plantages de filtres
                df_h = pd.DataFrame(columns=["Date", "Nom", "Montant", "Categorie", "Compte", "Mois", "Année"])
                liste_annees = [pd.Timestamp.now().year]
            else:
                df_h = st.session_state.df.copy()
                if "Année" not in df_h.columns:
                    df_h["Année"] = df_h["Date"].dt.year
                
                # On s'assure que les années sont bien des entiers uniques
                annees_brutes = df_h['Année'].dropna().unique()
                liste_annees = sorted([int(a) for a in annees_brutes], reverse=True)

            # 1. LES SÉLECTEURS (Une seule déclaration par widget !)
            cols_filtres = st.columns([1, 1, 1, 1])
            
            with cols_filtres[0]:
                # UNIQUE sélecteur pour le profil
                choix_actuel = st.selectbox(
                    "🎯 Profil", 
                    ["Tout le monde"] + st.session_state.groupes_liste, 
                    key="choix_g"
                )

            # --- LOGIQUE DE FILTRAGE PAR PROFIL ET CALCULS DYNAMIQUES ---
            choix_actuel = st.session_state.choix_g
            df_h = st.session_state.df.copy()

            # Définition des comptes du groupe
            if choix_actuel != "Tout le monde":
                cps = [c for c, cfg in st.session_state.config_groupes.items() if cfg.get("Groupe") == choix_actuel]
                obj = sum([v.get("Objectif", 0.0) for k, v in st.session_state.config_groupes.items() if v.get("Groupe") == choix_actuel])
            else:
                cps = list(st.session_state.config_groupes.keys())
                obj = sum([v.get("Objectif", 0.0) for v in st.session_state.config_groupes.values()])

            # --- CORRECTION : DÉCLARATION UNIQUE DU FILTRE DE CATÉGORIES ---
            # On le place ici pour qu'il soit créé une seule fois au chargement de la page Analyses
            categories_detectees = st.session_state.df['Categorie'].unique().tolist() if not st.session_state.df.empty else []
            virements_techniques = [c for c in categories_detectees if "🔄" in str(c) or "VERS " in str(c).upper() or "INTERNE" in str(c).upper()]
            # On définit les catégories disponibles basées sur le groupe actuel
            df_temp_filtre = df_h[df_h["Compte"].isin(cps)]
            categories_dispo = sorted(df_temp_filtre['Categorie'].unique()) if not df_temp_filtre.empty else []
            
            
            # --- CALCUL DES SOLDES RÉELS ---
            soldes_depart = {str(c).strip(): st.session_state.config_groupes[c].get("Solde", 0.0) for c in cps}
            
            # CORRECTION ICI : On s'assure que les années sont des entiers et sans valeurs vides
            annees_brutes = df_h['Année'].dropna().unique().tolist()
            liste_annees = sorted([int(a) for a in annees_brutes], reverse=True)
            
            with cols_filtres[1]:
                # Maintenant annee_choisie sera un entier pur (ex: 2025)
                annee_choisie = st.selectbox("📅 Année", liste_annees)

            # On s'assure aussi que la colonne Année du DataFrame est bien numérique pour la comparaison
            df_h["Année"] = pd.to_numeric(df_h["Année"], errors='coerce')
            
            soldes_finaux = mettre_a_jour_soldes(df_h[df_h["Compte"].isin(cps)], soldes_depart)
            solde_global = sum(soldes_finaux.values())

            # On prépare df_dash pour les visuels (filtré par année)
            df_dash = df_h[df_h["Compte"].isin(cps) & (df_h["Année"] == annee_choisie)].copy()

            # --- FILTRAGE PAR MOIS ---
            liste_m = sorted(df_dash['Mois'].unique(), key=lambda x: NOMS_MOIS.index(x) if x in NOMS_MOIS else 0)
            with cols_filtres[2]:
                mois_choisi = st.selectbox("📆 Mois", liste_m)

            # Données réelles pour les graphiques
            df_reel = df_dash[~df_dash["Categorie"].isin(virements_techniques)].copy()

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
            config_master = st.session_state.get('config_groupes', {})

            for i, c in enumerate(cps):
                nom_propre = str(c).strip()
                val = soldes_finaux.get(nom_propre.upper(), 0.0) 
                
                # MODIFICATION : Lecture directe de la couleur mise à jour par le picker
                couleur_compte = st.session_state.config_groupes.get(nom_propre, {}).get("Couleur", "#3498db")

                with cols_kpi[i+1]:
                    st.markdown(f"""
                        <div style="background-color: {couleur_compte}; padding: 15px; border-radius: 12px; text-align: center; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);">
                            <p style="margin: 0; font-size: 11px; color: white; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-transform: uppercase;">{nom_propre}</p>
                            <p style="margin: 0; font-size: 18px; color: white; font-weight: 700;">{val:,.2f} €</p>
                        </div>
                    """, unsafe_allow_html=True)

            # Données Annuelles
            annee_max = annee_choisie
            df_dash['Date'] = pd.to_datetime(df_dash['Date'], dayfirst=True, errors='coerce')

            # Maintenant le .dt.year fonctionnera
            df_ann = df_reel[pd.to_datetime(df_reel['Date'], dayfirst=True).dt.year == annee_max].groupby('Mois').agg(
                Revenus=('Montant', lambda x: x[x > 0].sum()),
                Dépenses=('Montant', lambda x: abs(x[x < 0].sum()))
            ).reset_index()
            
            df_tab = pd.DataFrame({'Mois': NOMS_MOIS})

            for c in cps:
                s_init_compte = st.session_state.config_groupes[c].get("Solde", 0.0)
                mouvements = df_dash[df_dash["Compte"] == c].groupby("Mois")["Montant"].sum().reset_index()
                df_c = pd.merge(pd.DataFrame({'Mois': NOMS_MOIS}), mouvements, on='Mois', how='left').fillna(0)
                df_tab[c] = s_init_compte + df_c["Montant"].cumsum()

            df_tab = pd.merge(df_tab, df_ann[['Mois', 'Revenus', 'Dépenses']], on='Mois', how='left').fillna(0)
            df_tab['Épargne'] = df_tab['Revenus'] - df_tab['Dépenses']
            df_tab['Patrimoine'] = df_tab[cps].sum(axis=1)

            c_recap, c_ann, c_graph = st.columns([1, 1, 1])

            with c_recap:
                st.markdown(f"### 📋 Détails {mois_choisi} {annee_choisie}")
                
                # PRÉPARER LES DONNÉES DU MOIS
                df_m = df_dash[(df_dash['Mois'] == mois_choisi) & (df_dash['Année'] == annee_choisie)].sort_values("Date", ascending=False)
                
                is_vir = df_m['Categorie'].str.upper().isin([c.upper() for c in virements_techniques])
                df_virs = df_m[is_vir]
                df_dep = df_m[(df_m['Montant'] < 0) & (~is_vir)]
                df_rev = df_m[(df_m['Montant'] > 0) & (~is_vir)]

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
                    df_b = df_m[(df_m['Montant'] < 0) & (~df_m['Categorie'].isin(liste_exclusion))]
                    
                    if not df_b.empty:
                        df_res = df_b.groupby("Categorie")["Montant"].sum().abs().reset_index().sort_values("Montant")
                        fig_b = px.bar(df_res, x="Montant", y="Categorie", orientation='h')
                        
                        max_val = df_res["Montant"].max()
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
                        df_template = pd.DataFrame({'Mois': NOMS_MOIS})
                        if not df_dash.empty:
                            # CORRECTION : On crée un DataFrame sans les virements internes pour le calcul
                            df_flux_reels = df_dash[~df_dash["Categorie"].isin(virements_techniques)].copy()

                            # 1. On crée le récap sur les flux réels uniquement
                            df_reel_mois = df_flux_reels.groupby('Mois')['Montant'].agg(
                                Revenus=lambda x: x[x > 0].sum(),
                                Dépenses=lambda x: abs(x[x < 0].sum())
                            ).reset_index()

                            # 2. CRÉATION DE LA STRUCTURE COMPLÈTE (Jan à Déc)
                            df_tab = pd.merge(df_template, df_reel_mois, on='Mois', how='left').fillna(0)

                            # 3. On calcule l'épargne mensuelle
                            df_tab['Épargne'] = df_tab['Revenus'] - df_tab['Dépenses']
                            
                            # 4. Tri chronologique
                            df_tab['Mois_idx'] = df_tab['Mois'].apply(lambda x: NOMS_MOIS.index(x))
                            df_tab = df_tab.sort_values('Mois_idx')

                            # 5. Calcul du Patrimoine cumulé
                            # Note : Le patrimoine doit inclure les virements (car l'argent bouge mais ne sort pas)
                            # Mais ici on le base sur l'épargne (Revenus - Dépenses sans virements), ce qui est mathématiquement identique
                            solde_depart_annee = sum(st.session_state.config_groupes[c].get("Solde", 0.0) for c in cps)
                            df_tab['Patrimoine'] = solde_depart_annee + df_tab['Épargne'].cumsum()

                            # --- AFFICHAGE DU TABLEAU ORIGINAL ---
                            h1, h2, h3, h4, h5 = st.columns([1.2, 1, 1, 1.2, 1.3])
                            base_h = "margin:0; font-weight:bold; font-size:10px; color:gray;"
                            
                            h1.markdown(f"<p style='{base_h} text-align:Center;'>MOIS</p>", unsafe_allow_html=True)
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
                                    
                                    c1.markdown(f"<p style='{base_d} text-align:left; opacity:{opacity};'>{row['Mois']}</p>", unsafe_allow_html=True)
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
                                df_dep = df_dash[df_dash['Montant'] < 0].copy()
                                df_dep['Montant'] = df_dep['Montant'].abs()

                                # 2. Création du Pivot avec TOUS les mois
                                pivot_cat = df_dep.pivot_table(
                                    index='Categorie', 
                                    columns='Mois', 
                                    values='Montant', 
                                    aggfunc='sum'
                                ).fillna(0)

                                for m in NOMS_MOIS:
                                    if m not in pivot_cat.columns:
                                        pivot_cat[m] = 0.0
                                
                                pivot_cat = pivot_cat[NOMS_MOIS]
                                pivot_cat['Total'] = pivot_cat.sum(axis=1)

                                # --- CSS AJUSTÉ POUR LE SYMBOLE € ---
                                # On réduit un peu la taille (9.5px) pour compenser l'ajout du symbole
                                style_texte = "margin:0; font-weight:bold; font-size:9.5px; white-space: nowrap; overflow: hidden;"
                                
                                # --- EN-TÊTES ---
                                cols = st.columns([3] + [0.8] * 12 + [1.3]) # On élargit un peu le total final
                                
                                cols[0].markdown(f"<p style='{style_texte} text-align:left; color:gray;'>CATÉGORIE</p>", unsafe_allow_html=True)
                                for i, mois in enumerate(NOMS_MOIS):
                                    cols[i+1].markdown(f"<p style='{style_texte} text-align:center; color:gray;'>{mois[:3].upper()}</p>", unsafe_allow_html=True)
                                cols[-1].markdown(f"<p style='{style_texte} text-align:right; color:gray;'>TOTAL</p>", unsafe_allow_html=True)

                                st.markdown("<div style='margin-top: -5px;'></div>", unsafe_allow_html=True)

                                with st.container(height=400):
                                    for cat, row in pivot_cat.iterrows():
                                        c = st.columns([3] + [0.8] * 12 + [1.3])
                                        
                                        # 1. Nom de la catégorie
                                        nom_cat = cat[:14] + ".." if len(cat) > 14 else cat
                                        c[0].markdown(f"<p style='{style_texte} text-align:left;' title='{cat}'>{nom_cat}</p>", unsafe_allow_html=True)
                                        
                                        # 2. Valeurs par mois avec le symbole €
                                        for i, mois in enumerate(NOMS_MOIS):
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
                        
                        # 1. Calcul du solde de départ cumulé (fixe) pour ce profil
                        solde_depart_total = sum(st.session_state.config_groupes[c].get("Solde", 0.0) for c in cps)
                        
                        # 2. Calcul du solde actuel (incluant les transactions s'il y en a)
                        # Si aucune transaction, solde_actuel sera égal à solde_depart_total
                        solde_actuel = sum(soldes_finaux.get(str(c).strip().upper(), 0.0) for c in cps)

                        if obj > 0:
                            # 3. Calcul de l'épargne réalisée (le surplus)
                            epargne_realisee = solde_actuel - solde_depart_total
                            
                            # 4. Calcul de la progression (0% si on n'a pas encore épargné)
                            # On utilise max(0) pour ne pas avoir de barre négative si on a dépensé du capital
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

                            st.markdown(f"""
                                <div style="background:#e0e0e0; border-radius:5px; height:12px; margin-bottom:5px; width:100%;">
                                    <div style="background:{couleur_barre}; width:{prog*100}%; height:12px; border-radius:5px; transition: width 0.8s ease-in-out;"></div>
                                </div>
                                <p style='font-size:10px; color:gray; margin:0;'>Cible de fin d'année : {(solde_depart_total + obj):,.0f}€</p>
                                """, unsafe_allow_html=True)
        
                            # On complète df_tab avec les colonnes de chaque compte pour le graphique d'évolution
                        for c in cps:
                            nom_c = str(c).strip()
                            # Calcul du flux mensuel par compte
                            df_c = df_dash[df_dash['Compte'] == nom_c].groupby('Mois')['Montant'].sum().reset_index()
                            df_c.columns = ['Mois', nom_c]
                            
                            # Fusion avec le tableau principal
                            df_tab = pd.merge(df_tab, df_c, on='Mois', how='left').fillna(0)
                            
                            # Calcul du solde progressif pour ce compte précis
                            # Solde initial du compte + cumul des flux de l'année
                            s_init_c = st.session_state.config_groupes.get(nom_c, {}).get("Solde", 0.0)
                            if nom_c in df_tab.columns:
                                df_tab[nom_c] = s_init_c + df_tab[nom_c].cumsum()
                            else:
                                # Si le compte n'a pas de mouvements, son solde reste le solde initial
                                df_tab[nom_c] = s_init_c

                    # --- 2. Flux Mensuels (Avec Dégradé Vertical) ---
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

                                # Ajout des traces avec le dégradé
                        fig_p.add_trace(go.Scatter(
                                    x=df_tab["Mois"], y=df_tab["Revenus"], name="Rev.", 
                                    fill='tozeroy', 
                                    line=dict(color=col_rev, width=2),
                                    fillgradient=appliquer_gradient(col_rev)
                                ))

                        fig_p.add_trace(go.Scatter(
                                    x=df_tab["Mois"], y=df_tab["Dépenses"], name="Dép.", 
                                    fill='tozeroy', 
                                    line=dict(color=col_perf_dep, width=2),
                                    fillgradient=appliquer_gradient(col_perf_dep)
                                ))

                        fig_p.add_trace(go.Scatter(
                                    x=df_tab["Mois"], y=df_tab["Épargne"], name="Épar.", 
                                    fill='tozeroy', 
                                    line=dict(color=col_epargne, width=2),
                                    fillgradient=appliquer_gradient(col_epargne)
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
                                    xaxis=dict(showgrid=False, tickfont=dict(size=10, color="gray")),
                                    yaxis=dict(showgrid=False, visible=False)
                                )

                        st.plotly_chart(fig_p, width='content', config={'displayModeBar': False},key=f"flux_{choix_actuel}_{annee_choisie}")
                                


                                            # --- PRÉPARATION DES DONNÉES PAR COMPTE ---
                        for c in cps:
                                nom_c = str(c).strip()
                                df_mouv = df_dash[df_dash['Compte'] == nom_c].groupby('Mois')['Montant'].sum().reset_index()
                                df_mouv.columns = ['Mois', 'Mouv_Mois']
                                df_tab = pd.merge(df_tab, df_mouv, on='Mois', how='left').fillna(0)
                                
                                solde_initial_historique = st.session_state.config_groupes.get(nom_c, {}).get("Solde", 0.0)
                                mouvements_passes = st.session_state.df[
                                    (st.session_state.df['Compte'] == nom_c) & 
                                    (st.session_state.df['Année'] < annee_choisie)
                                ]['Montant'].sum()
                                
                                solde_au_depart = solde_initial_historique + mouvements_passes
                                df_tab[nom_c] = solde_au_depart + df_tab['Mouv_Mois'].cumsum()
                                df_tab = df_tab.drop(columns=['Mouv_Mois'])


                                                # --- 3. Évolution Patrimoine (Dynamique avec Transparence) ---
                        df_tab['Patrimoine'] = df_tab[cps].sum(axis=1)
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
                                    x=df_tab["Mois"], 
                                    y=df_tab[nom_c], 
                                    name=nom_c, 
                                    stackgroup='one', 
                                    line=dict(color=couleur_hex, width=1.5),
                                    fillgradient=dict(
                                        type='vertical', 
                                        colorscale=[(0, c_stop), (1, c_start)]
                                    ),
                                    hoverinfo='x+y+name'
                                ))
                                        
                            # Ajout du TOTAL (Ligne pointillée)
                        fig_e.add_trace(go.Scatter(
                                x=df_tab["Mois"], 
                                y=df_tab["Patrimoine"], 
                                name="TOTAL", 
                                line=dict(color=col_patri, width=3, dash='dot')
                            ))

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
                            # On filtre df_dash (qui est déjà filtré par Année et Groupe) pour n'avoir que le mois choisi
                            df_mois = df_dash[df_dash['Mois'] == mois_choisi].copy()
                            
                            # On ne garde que les dépenses (Montant < 0)
                            depenses_groupe = df_mois[df_mois['Montant'] < 0]
                            
                            if not depenses_groupe.empty:
                                # On somme par catégorie
                                stats_depenses = depenses_groupe.groupby('Categorie')['Montant'].sum().abs().to_dict()

                        # 2. Chargement et Agrégation des Budgets GSheets
                        # On doit récupérer les budgets de TOUS les comptes du groupe (cps)
                        budgets_cumules = {}
                        
                        try:
                            df_all_gsheet = conn.read(worksheet="Budgets", ttl=0)
                            # Filtre sur l'user, le mois choisi et les comptes appartenant au groupe (cps)
                            mask_b = (
                                (df_all_gsheet['username'] == user) & 
                                (df_all_gsheet['Mois'] == mois_choisi) & 
                                (df_all_gsheet['Compte'].isin(cps)) &
                                (df_all_gsheet['Type'] == 'Categorie')
                            )
                            df_budget_groupe = df_all_gsheet[mask_b]
                            
                            if not df_budget_groupe.empty:
                                # On cumule les sommes par catégorie (si "Courses" est sur 2 comptes du groupe)
                                budgets_cumules = df_budget_groupe.groupby('Nom')['Somme'].sum().to_dict()
                        except Exception as e:
                            st.error(f"Erreur lors de la lecture des budgets : {e}")

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
                                    rev = df_dash[df_dash['Montant'] > 0]['Montant'].sum()
                                    dep = abs(df_dash[df_dash['Montant'] < 0]['Montant'].sum())
                                    epargne_physique_cumulee = rev - dep
                                else:
                                    epargne_physique_cumulee = 0.0

                            # Le solde global pour la simulation (par défaut le patrimoine actuel)
                            solde_bancaire_actuel = epargne_physique_cumulee

                            # 2. LECTURE DES DONNÉES
                            try:
                                df_projets_gsheet = conn.read(worksheet="Projets", ttl=300)
                                mask = (df_projets_gsheet['username'] == user) & (df_projets_gsheet['Profil'] == choix_actuel)
                                mes_projets_df = df_projets_gsheet[mask].copy()
                                mes_projets_df['Date'] = pd.to_datetime(mes_projets_df['Date'], format='%Y-%m-%d', errors='coerce')
                                mes_projets_df['Cout'] = pd.to_numeric(mes_projets_df['Cout'], errors='coerce')
                                if 'Capa' not in mes_projets_df.columns: mes_projets_df['Capa'] = 0.0
                                mes_projets_df['Capa'] = pd.to_numeric(mes_projets_df['Capa'], errors='coerce').fillna(0.0)
                                mes_projets_df = mes_projets_df.sort_values('Date')
                            except:
                                mes_projets_df = pd.DataFrame()

                            # 3. PARAMÈTRES
                            with st.container(border=True):
                                epargne_depart_simu = st.number_input("💰 Solde de départ pour simulation (€)", value=solde_bancaire_actuel, key="input_simu_depart")
                                st.caption(f"Épargne réelle cumulée : {epargne_physique_cumulee:,.2f}€")

                            # 4. NOUVEAU PROJET
                            st.markdown(f"➕ Nouveau projet")
                            with st.container(border=True):
                                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                                with c1: nom_p = st.text_input("Nom", key="new_proj_nom")
                                with c2: cout_p = st.number_input("Coût (€)", min_value=0.0, key="new_proj_cout")
                                with c3: date_p = st.date_input("Échéance", min_value=datetime.now(), key="new_proj_date")
                                with c4: capa_p = st.number_input("Épargne/m", min_value=0.0, key="new_proj_capa")
                                
                                if st.button("🚀 Enregistrer le projet", width='stretch'):
                                    if nom_p:
                                        try:
                                            df_actuel = conn.read(worksheet="Projets", ttl=0)
                                            nouvelle_ligne = pd.DataFrame([{
                                                "username": str(user),
                                                "Profil": str(choix_actuel),
                                                "Nom": str(nom_p),
                                                "Cout": float(cout_p),
                                                "Date": date_p.strftime('%Y-%m-%d'),
                                                "Capa": float(capa_p)
                                            }])
                                            df_maj = pd.concat([df_actuel, nouvelle_ligne], ignore_index=True)
                                            conn.update(worksheet="Projets", data=df_maj)
                                            
                                            # --- REFRESH & NAVIGATION ---
                                            st.cache_data.clear()
                                            st.session_state["active_tab"] = "Projets" # On s'assure de rester ici
                                            relancer_avec_succes()
                                        except Exception as e:
                                            st.error(f"Erreur : {e}")

                            # 5. LISTE ET CALCULS
                            st.markdown(f"🚧 Mes projets")
                            if not mes_projets_df.empty:
                                solde_cascade = epargne_depart_simu
                                cumul_epargne_reel_restant = epargne_physique_cumulee 
                                date_ref = datetime.now()

                                for index, p in mes_projets_df.iterrows():
                                    if pd.isna(p['Date']): continue
                                    
                                    d_p = p['Date']
                                    nb_mois = max(0, (d_p.year - date_ref.year) * 12 + (d_p.month - date_ref.month))
                                    cout_projet = float(p['Cout'])
                                    capa_projet = float(p.get('Capa', 0.0))
                                    
                                    # --- CALCULS ---
                                    # On compare l'épargne réelle restante au coût du projet
                                    ratio_reel = min(max(cumul_epargne_reel_restant / cout_projet, 0.0), 1.0) if cout_projet > 0 else 1.0
                                    montant_reel_affiche = min(cumul_epargne_reel_restant, cout_projet)

                                    # Simulation : solde cascade (ce qui restait des projets précédents) + épargne mensuelle
                                    argent_total_futur = solde_cascade + (capa_projet * nb_mois)
                                    ratio_futur = min(max(argent_total_futur / cout_projet, 0.0), 1.0) if cout_projet > 0 else 1.0
                                    montant_futur_affiche = min(argent_total_futur, cout_projet)

                                    with st.container(border=True):
                                        col_txt, col_stat = st.columns([3, 1])
                                        with col_txt:
                                            st.write(f"### {p['Nom']}")
                                            st.caption(f"📅 {d_p.strftime('%d/%m/%Y')} | 📈 {capa_projet}€/mois")
                                            
                                            # Affichage avec % et €
                                            st.progress(ratio_reel, text=f"Épargne Réelle : {int(ratio_reel*100)}% ({montant_reel_affiche:,.2f}€ / {cout_projet:,.2f}€)")
                                            st.progress(ratio_futur, text=f"Projection : {int(ratio_futur*100)}% ({montant_futur_affiche:,.2f}€ / {cout_projet:,.2f}€)")
                                        with col_stat:
                                            with st.popover("✏️"):
                                                st.write(f"**Modifier {p['Nom']}**")
                                                n_cout = st.number_input("Coût (€)", value=float(p['Cout']), key=f"c_{index}")
                                                n_capa = st.number_input("Épargne / mois (€)", value=capa_projet, key=f"cap_{index}")
                                                n_date = st.date_input("Date échéance", value=d_p, key=f"d_{index}")
                                                
                                                if st.button("Enregistrer les modifs", key=f"s_{index}", width='stretch', type="primary"):
                                                    df_f = conn.read(worksheet="Projets", ttl=0)
                                                    m = (df_f['username'] == user) & (df_f['Nom'] == p['Nom']) & (df_f['Profil'] == choix_actuel)
                                                    
                                                    df_f.loc[m, 'Cout'] = n_cout
                                                    df_f.loc[m, 'Capa'] = n_capa
                                                    df_f.loc[m, 'Date'] = n_date.strftime('%Y-%m-%d')
                                                    
                                                    conn.update(worksheet="Projets", data=df_f)
                                                    st.cache_data.clear()
                                                    st.session_state["active_tab"] = "Projets"
                                                    relancer_avec_succes()

                                            if argent_total_futur >= cout_projet:
                                                st.success(f"Faisable")
                                                solde_cascade = argent_total_futur - cout_projet
                                                cumul_epargne_reel_restant = max(0.0, cumul_epargne_reel_restant - cout_projet)
                                            else:
                                                st.error(f"Il Manquera {cout_projet - argent_total_futur:,.2f}€ à l'échéance")
                                                solde_cascade = 0
                                                cumul_epargne_reel_restant = 0
                                            
                                            date_ref = d_p
                                            if st.button("🗑️", key=f"del_{index}"):
                                                df_f = conn.read(worksheet="Projets", ttl=0)
                                                m_del = (df_f['username'] == user) & (df_f['Nom'] == p['Nom']) & (df_f['Profil'] == choix_actuel)
                                                conn.update(worksheet="Projets", data=df_f.drop(df_f[m_del].index))
                                                st.cache_data.clear()
                                                st.session_state["active_tab"] = "Projets"
                                                relancer_avec_succes()
                            else:
                                st.info(f"Aucun projet pour {choix_actuel}")


                                
    # Initialisation de l'état d'affichage par mois (True par défaut)
    if "show_prev_mois" not in st.session_state:
        st.session_state.show_prev_mois = {m: True for m in NOMS_MOIS}

    elif selected == "Prévisionnel":
        # --- 1. INITIALISATION CLOUD ---
        if "df_prev" not in st.session_state:
            st.session_state.df_prev = charger_previsions()

        # --- 2. FILTRES COMPACTS ---
        cols_f = st.columns([1, 1, 1, 1])
        with cols_f[0]:
            choix_g = st.selectbox("🎯 Profil", ["Tout le monde"] + st.session_state.groupes_liste, key="prev_g")
        
        cps = [c for c, cfg in st.session_state.config_groupes.items() if cfg.get("Groupe") == choix_g] if choix_g != "Tout le monde" else list(st.session_state.config_groupes.keys())
        
        # CORRECTION ICI : On s'assure que chaque année est un entier (int) et on enlève les valeurs nulles
        annees_df = st.session_state.df['Année'].dropna().unique().tolist()
        liste_a = sorted(list(set([int(a) for a in annees_df] + [int(time.localtime().tm_year)])), reverse=True)
        
        with cols_f[1]:
            # Maintenant liste_a ne contient que des entiers
            annee_p = st.selectbox("📅 Année", liste_a, key="prev_a")
        
        with cols_f[2]:
            liste_mois_select = ["Tous les mois"] + NOMS_MOIS
            mois_p = st.selectbox("📆 Mois", liste_mois_select, index=time.localtime().tm_mon, key="prev_m")

        # --- 3. CALCULS ---
        categories_detectees = st.session_state.df['Categorie'].unique().tolist() if not st.session_state.df.empty else []
        virements_techniques = [c for c in categories_detectees if "🔄" in str(c) or "VERS " in str(c).upper() or "INTERNE" in str(c).upper()]
        
        mois_idx_fin = NOMS_MOIS.index(mois_p) if mois_p != "Tous les mois" else 11
        annee_p_int = int(annee_p)

        # A. Préparation des données
        df_reel_filtre = st.session_state.df[st.session_state.df["Compte"].isin(cps)].copy()
        df_prev_filtre = st.session_state.df_prev[st.session_state.df_prev["Compte"].isin(cps)].copy()
        
        # Sécurité format date (format français)
        df_reel_filtre["Date"] = pd.to_datetime(df_reel_filtre["Date"], dayfirst=True, errors='coerce')

        # B. CALCUL DES SOLDES (LOGIQUE DE TRANSFERT UNIQUE)
        soldes_finaux_comptes = {}
        # Initialisation propre avec les clés en MAJUSCULES
        for c in cps:
            nom_c_upper = str(c).strip().upper()
            solde_initial_config = float(st.session_state.config_groupes.get(c, {}).get("Solde", 0.0))
            soldes_finaux_comptes[nom_c_upper] = solde_initial_config

        # 1. Traitement du RÉEL (CSV)
        for _, ligne in df_reel_filtre.iterrows():
            mnt = float(ligne['Montant'])
            cpte_source = str(ligne['Compte']).strip().upper()
            cat = str(ligne['Categorie']).upper()

            # Impact source
            if cpte_source in soldes_finaux_comptes:
                soldes_finaux_comptes[cpte_source] += mnt
            
            # Impact cible (Transfert interne)
            if "🔄" in cat or "VERS" in cat or "INTERNE" in cat:
                for nom_c_cible in soldes_finaux_comptes.keys():
                    if nom_c_cible != cpte_source and any(m in cat for m in nom_c_cible.split() if len(m) > 2):
                        if mnt < 0:
                            soldes_finaux_comptes[nom_c_cible] += abs(mnt)
                        else:
                            soldes_finaux_comptes[nom_c_cible] -= abs(mnt)
                        break

        # 2. Traitement du PRÉVISIONNEL
        mask_p = (df_prev_filtre["Année"] < annee_p_int) | \
                 ((df_prev_filtre["Année"] == annee_p_int) & 
                  (df_prev_filtre["Mois"].apply(lambda x: NOMS_MOIS.index(x) <= mois_idx_fin if x in NOMS_MOIS else False)))
        
        df_p_periode = df_prev_filtre[mask_p]

        for _, ligne in df_p_periode.iterrows():
            if st.session_state.show_prev_mois.get(ligne['Mois'], True):
                mnt = float(ligne['Montant'])
                cpte_source = str(ligne['Compte']).strip().upper()
                cat = str(ligne['Categorie']).upper()

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
            df_reel_filtre[df_reel_filtre["Année"] == annee_p_int],
            df_prev_filtre[df_prev_filtre["Année"] == annee_p_int]
        ], ignore_index=True)
        
        df_tab_data = df_combi.copy()
        # Suppression des prévisions si l'oeil est fermé
        for m, visible in st.session_state.show_prev_mois.items():
            if not visible:
                idx_a_supprimer = df_tab_data[(df_tab_data["Mois"] == m) & (df_tab_data["Nom"].str.contains(r"\[PRÉVI\]", na=False))].index
                df_tab_data = df_tab_data.drop(idx_a_supprimer)

        stats = df_tab_data.groupby('Mois')['Montant'].agg(
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

        with col1:
            st.markdown("##### ➕ Ajouter Prévisions")
            
            # 1. On définit la liste des catégories
            # On mélange ta liste fixe (complète) avec les catégories uniques du DF pour ne rien louper
            if not st.session_state.df.empty:
                cats_du_df = st.session_state.df['Categorie'].unique().tolist()
                # On fusionne avec ta liste globale et on enlève les doublons avec set()
                cats = sorted(list(set(LISTE_CATEGORIES_COMPLETE + cats_du_df)))
            else:
                cats = sorted(LISTE_CATEGORIES_COMPLETE)
            if "lignes_indices" not in st.session_state:
                st.session_state.lignes_indices = [0]

            # 2. LE FORMULAIRE (Contient uniquement les champs et le bouton de validation final)
            with st.form("bulk_add_form_v4"):
                nouvelles_previs = []
                
                for idx in st.session_state.lignes_indices:
                    with st.container():
                                                # À l'intérieur de ta boucle for idx...
                        c1, c2, c_eur = st.columns([2, 0.8, 0.2]) # On ajoute la colonne pour l'Euro
                        nom = c1.text_input("Libellé", key=f"n_{idx}", label_visibility="collapsed", placeholder="Nom...")
                        mnt = c2.number_input("Montant", key=f"m_{idx}", label_visibility="collapsed", step=10.0, format="%.2f")
                        c_eur.markdown("<p style='margin-top:7px; font-weight:bold; color:gray;'>€</p>", unsafe_allow_html=True)
                        
                        c_cat, c_cpte, c_date = st.columns([1, 1, 1])
                        cat = c_cat.selectbox("Cat", cats, key=f"cat_{idx}", label_visibility="collapsed")
                        cpte = c_cpte.selectbox("Compte", cps, key=f"cp_{idx}", label_visibility="collapsed")
                        def_date = pd.Timestamp(year=annee_p_int, month=mois_idx_fin + 1 if mois_idx_fin < 11 else 1, day=1)
                        dte = c_date.date_input("Date", value=def_date, key=f"d_{idx}", label_visibility="collapsed")
                        
                        nouvelles_previs.append({"Date": dte, "Nom": nom, "Montant": mnt, "Categorie": cat, "Compte": cpte})
                        st.markdown("<hr style='margin:10px 0; opacity:0.1;'>", unsafe_allow_html=True)

                # SEUL ce bouton est autorisé dans le formulaire
                submit = st.form_submit_button("Enregistrer les prévisions 💾", width='stretch', type="primary")

            # --- 3. LES BOUTONS DE GESTION (HORS DU FORMULAIRE) ---
            # Ces boutons sont maintenant APRES le bloc "with st.form"
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])

            if col_btn1.button("➕ Ligne", width='stretch'):
                prochain_idx = max(st.session_state.lignes_indices) + 1 if st.session_state.lignes_indices else 0
                st.session_state.lignes_indices.append(prochain_idx)
                relancer_avec_succes()

            if col_btn2.button("🗑️ Ligne", width='stretch'):
                if len(st.session_state.lignes_indices) > 1:
                    st.session_state.lignes_indices.pop()
                    relancer_avec_succes()

            if col_btn3.button("🔄 Reset", width='stretch'):
                st.session_state.lignes_indices = [0]
                relancer_avec_succes()

            # 4. Logique de sauvegarde (S'exécute quand submit est True)
            if submit:
                lignes_a_sauver = [l for l in nouvelles_previs if l["Nom"].strip() != ""]
                if lignes_a_sauver:
                    df_new = pd.DataFrame(lignes_a_sauver)
                    df_new["Date"] = pd.to_datetime(df_new["Date"])
                    df_new["Nom"] = "[PRÉVI] " + df_new["Nom"]
                    df_new["Mois"] = df_new["Date"].dt.month.apply(lambda x: NOMS_MOIS[x-1])
                    df_new["Année"] = df_new["Date"].dt.year
                    
                    st.session_state.df_prev = pd.concat([st.session_state.df_prev, df_new], ignore_index=True)
                    sauvegarder_previsions(st.session_state.df_prev, st.session_state["username"])
                    
                    st.session_state.lignes_indices = [0]
                    st.success("Enregistré !")
                    relancer_avec_succes()

        with col2: 
            st.markdown(f"##### 📋 Prévisions {mois_p}")
            
            # Filtrage des données
            if mois_p == "Tous les mois":
                df_mois_prev = df_combi[df_combi["Nom"].str.contains(r"\[PRÉVI\]", na=False)]
            else:
                df_mois_prev = df_combi[(df_combi["Mois"] == mois_p) & (df_combi["Nom"].str.contains(r"\[PRÉVI\]", na=False))]
                
            with st.container(height=480):
                if not df_mois_prev.empty:
                    # Tri par date pour plus de clarté
                    for idx, r in df_mois_prev.sort_values("Date").iterrows():
                        c1, c2, c3 = st.columns([3.5, 1.5, 0.7]) # Ajustement léger des largeurs
                        
                        # Formatage des infos secondaires (Date + Compte)
                        # On vérifie si la date existe (n'est pas nulle/NaT) avant de formater
                        date_str = r['Date'].strftime('%d/%m') if pd.notnull(r['Date']) else "??/??"
                        nom_propre = r['Nom'].replace('[PRÉVI] ','')
                        compte_nom = r['Compte']
                        
                        # Affichage HTML : Nom en gras, puis Date | Compte | Catégorie en petit gris
                        c1.markdown(f"""
                            <div style='line-height:1.2;'>
                                <b style='font-size:13px;'>{nom_propre}</b><br>
                                <small style='color:gray;'>{date_str} • {compte_nom} • {r['Categorie']}</small>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        # Montant
                        color = col_rev if r['Montant'] > 0 else col_perf_dep
                        c2.markdown(f"<p style='color:{color}; font-weight:bold; text-align:right; margin:0; font-size:14px;'>{r['Montant']:.0f}€</p>", unsafe_allow_html=True)
                        
                        # Bouton Supprimer
                        if c3.button("", icon=":material/delete:", key=f"del_{idx}", width='stretch'):
                            # Suppression précise par index
                            st.session_state.df_prev = st.session_state.df_prev.drop(st.session_state.df_prev[st.session_state.df_prev['Nom'] == r['Nom']].index[0])
                            sauvegarder_previsions(st.session_state.df_prev, st.session_state["username"])
                            relancer_avec_succes()
                            
                        st.markdown("<hr style='margin:4px 0; opacity:0.1;'>", unsafe_allow_html=True)
                else:
                    st.info("Rien de prévu.")

       # Calcul du point de départ au 1er janvier de l'année sélectionnée pour TOUS les comptes du profil
        # 1. Somme des soldes initiaux saisis en config
        base_config = 0.0
        for c in cps:
            base_config += float(st.session_state.config_groupes.get(c, {}).get("Solde", 0.0))

        # 2. Somme de tout le REEL (CSV) avant l'année en cours
        base_reel_passe = st.session_state.df[
            (st.session_state.df["Compte"].isin(cps)) & 
            (st.session_state.df["Année"] < annee_p_int)
        ]["Montant"].sum()

        # 3. Somme de toutes les PREVISIONS avant l'année en cours
        base_prev_passee = st.session_state.df_prev[
            (st.session_state.df_prev["Compte"].isin(cps)) & 
            (st.session_state.df_prev["Année"] < annee_p_int)
        ]["Montant"].sum()

        solde_base_annee = base_config + base_reel_passe + base_prev_passee

        with col3: 
            st.markdown("📊 Récap des prévisions annuel")
                    # MODIFICATION ICI : Utiliser df_tab_data au lieu de df_combi
            df_tab_p = pd.DataFrame({'Mois': NOMS_MOIS})
            mask_interne = df_tab_data['Categorie'].str.upper().str.contains("🔄|VERS|INTERNE", na=False)

            stats = df_tab_data[~mask_interne].groupby('Mois')['Montant'].agg(
                Rev=lambda x: x[x>0].sum(), 
                Dep=lambda x: abs(x[x<0].sum())
            ).reset_index()

            df_tab_p = pd.merge(df_tab_p, stats, on='Mois', how='left').fillna(0)
            df_tab_p['Epargne'] = df_tab_p['Rev'] - df_tab_p['Dep']
            df_tab_p['Solde'] = solde_base_annee + df_tab_p['Epargne'].cumsum()

            def get_gradient(hex_color):
                hex_c = hex_color.lstrip('#')
                r, g, b = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4))
                return dict(type='vertical', colorscale=[(0, f'rgba({r},{g},{b},0)'), (1, f'rgba({r},{g},{b},0.6)')])

            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(
                x=df_tab_p["Mois"], y=df_tab_p["Solde"],
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
            

           
            with st.container(height=340):
                for _, row in df_tab_p.iterrows():
                    m = row['Mois']
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
                            relancer_avec_succes()
                    


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
                
    elif selected == "Comptes":
            st.markdown("""
                <div style="background-color: rgba(255, 255, 255, 0.05); padding: 20px; border-radius: 15px; border: 1px solid rgba(128, 128, 128, 0.1); margin-bottom: 20px;">
                    <h2 style="margin: 0; font-size: 24px;">👥 Structure & Comptes</h2>
                    <p style="color: gray; font-size: 14px;">Organisez vos finances par groupes et configurez vos soldes de départ.</p>
                </div>
            """, unsafe_allow_html=True)

            # --- SECTION 1 : ARCHITECTURE (GROUPES & COMPTES REGROUPÉS) ---
            col_side1, col_config, col_notes, col_side2 = st.columns([1.5, 1, 1, 1.5])

            # --- POPOVER 1 : CONFIGURATION ---
            with col_config:
                with st.popover("⚙️ Ajouter des comptes bancaires/profils", width='stretch'):
                    tab_comptes, tab_groupes = st.tabs(["💳 Comptes","📁 profils"])
                    # ... (insère ici ton code de gestion des groupes et comptes) ...
                    st.info("Paramètres de structure")

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
                        sauvegarder_notes(note_text, st.session_state.username)
                        st.toast("Notes sauvegardées dans Google Sheets !")

                    # --- ONGLET 1 : GESTION DES GROUPES ---
                    with tab_groupes:
                        st.caption("Les profils permettent de segmenter votre patrimoine (ex: Commun, Théo, Aude, Entreprise ,...).")
                        
                        # Ajouter
                        n_g = st.text_input("Nom du nouveau profil", placeholder="Ex: votre Prénom", key="add_grp_input_unique")
                        if st.button("➕ Ajouter le profil", width='stretch'):
                            if n_g and n_g not in st.session_state.groupes_liste:
                                st.session_state.groupes_liste.append(n_g)
                                sauvegarder_groupes(st.session_state.groupes_liste, st.session_state.username)
                                st.toast(f"Groupe '{n_g}' ajouté !")
                                relancer_avec_succes()
                        
                        st.divider()
                        
                        # Supprimer
                        g_del = st.selectbox("Profil à supprimer", st.session_state.groupes_liste, key="sel_del_grp")
                        if st.button("🗑️ Supprimer le profil", width='stretch', type="secondary"):
                            if len(st.session_state.groupes_liste) > 1:
                                st.session_state.groupes_liste.remove(g_del)
                                sauvegarder_groupes(st.session_state.groupes_liste, st.session_state["username"])
                                st.warning(f"Groupe '{g_del}' supprimé")
                                relancer_avec_succes()

                    # --- ONGLET 2 : AJOUTER/SUPPRIMER DES COMPTES ---
                    with tab_comptes:
                        st.caption("Gérez les comptes qui n'ont pas d'import CSV (Manuels).")
                        
                        # Ajouter
                        n_compte_nom = st.text_input("Nom du compte à créer", placeholder="Ex: Livret A, CCP,...", key="input_new_cpte_unique")
                        if st.button("➕ Créer le compte", width='stretch'):
                            if n_compte_nom:
                                if n_compte_nom not in st.session_state.config_groupes:
                                    # On assigne le premier groupe par défaut
                                    groupe_defaut = st.session_state.groupes_liste[0] if st.session_state.groupes_liste else "Général"
                                    st.session_state.config_groupes[n_compte_nom] = {"Groupe": groupe_defaut, "Objectif": 0.0, "Solde": 0.0}
                                    sauvegarder_config(st.session_state.config_groupes, st.session_state["username"])
                                    st.toast(f"Compte '{n_compte_nom}' créé !")
                                    relancer_avec_succes()
                        
                        st.divider()

                        # Supprimer
                        comptes_existants = list(st.session_state.config_groupes.keys())
                        cpte_a_suppr = st.selectbox("Compte à supprimer", [""] + comptes_existants, key="del_cpte_select")
                        
                        if st.button("🗑️ Supprimer le compte", width='stretch', type="secondary"):
                            if cpte_a_suppr and cpte_a_suppr != "":
                                del st.session_state.config_groupes[cpte_a_suppr]
                                sauvegarder_config(st.session_state.config_groupes, st.session_state["username"])
                                st.warning(f"Compte '{cpte_a_suppr}' supprimé.")
                                relancer_avec_succes()

                st.markdown("<br>", unsafe_allow_html=True)

            # --- SECTION 2 : CONFIGURATION GÉNÉRALE (LA GRILLE) ---
            col_config, col_calc = st.columns([1.2, 0.8], gap="large")

            with col_config:
                st.markdown("### ⚙️ Configuration des soldes et objectifs")
                
                comptes_csv = df_h["Compte"].unique().tolist() if not df_h.empty else []
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
                            sauvegarder_config(st.session_state.config_groupes, st.session_state["username"])
                            st.success("Configuration sauvegardée avec succès !")
                            time.sleep(1)
                            relancer_avec_succes()
            with col_calc:
                st.markdown("### 🧮 Calculateur au Prorata")
                
                with st.container(border=True):
                    st.caption("Calculez la répartition équitable pour un compte commun.")
                    
                    # Entrées des revenus
                    sal_perso = st.number_input("Mon salaire net (€)", value=0.0, step=50.0)
                    sal_copine = st.number_input("Salaire partenaire (€)", value=0.0, step=50.0)
                    objectif_commun = st.number_input("Objectif commun total (€)", value=0.0, step=50.0)
                    
                    # Calculs logiques
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
                df_edit = pd.DataFrame(columns=["Date", "Nom", "Montant", "Categorie", "Compte", "Mois", "Année"])
                liste_annees = ["Toutes"]
            else:
                df_edit = df_h.copy().reset_index(drop=True)
                # Sécurité pour le format Date
                df_edit['Date'] = pd.to_datetime(df_edit['Date'], errors='coerce')
                df_edit['Année'] = df_edit['Date'].dt.year.fillna(0).astype(int)
                liste_annees = ["Toutes"] + sorted(df_edit['Année'].unique().astype(str).tolist(), reverse=True)

            df_f = df_edit.copy()
            
            # Filtrage (ne s'applique que si df_f n'est pas vide)
            if not df_f.empty:
                if st.session_state.filter_g != "Tous":
                    cps = [c for c,v in st.session_state.config_groupes.items() if v["Groupe"] == st.session_state.filter_g]
                    df_f = df_f[df_f["Compte"].isin(cps)]
                if st.session_state.filter_c != "Tous": 
                    df_f = df_f[df_f["Compte"] == st.session_state.filter_c]
                if st.session_state.filter_a != "Toutes": 
                    df_f = df_f[df_f["Année"] == int(st.session_state.filter_a)]
                if st.session_state.filter_m != "Tous": 
                    df_f = df_f[df_f["Mois"] == st.session_state.filter_m]

            # --- 3. MISE EN PAGE (S'affiche dans tous les cas) ---
            col_sidebar, col_add, col_main = st.columns([0.8, 1.2, 2.5], gap="small")

            # --- COLONNE 1 : FILTRES & CATÉGORIES ---
            with col_sidebar:
                @st.fragment
                def fragment_categorie():
                    st.markdown('<p style="font-weight:bold; color:#7f8c8d; margin-bottom:5px;">✨ Catégorie</p>', unsafe_allow_html=True)
                    
                    def valider_et_nettoyer():
                        emoji = st.session_state.get("emoji_choisi", "📁")
                        nom = st.session_state.get("input_new_cat", "").strip()
                        
                        if nom:
                            val_finale = f"{emoji} {nom}"
                            if sauvegarder_nouvelle_categorie(val_finale, st.session_state.username):
                                st.toast(f"✅ {val_finale} ajouté")
                                
                                # --- CORRECTION DE L'ERREUR ICI ---
                                # On vérifie si la liste existe, sinon on la crée à la volée
                                if 'LISTE_CATEGORIES_COMPLETE' not in st.session_state:
                                    st.session_state.LISTE_CATEGORIES_COMPLETE = []
                                
                                if val_finale not in st.session_state.LISTE_CATEGORIES_COMPLETE:
                                    st.session_state.LISTE_CATEGORIES_COMPLETE.append(val_finale)
                                    st.session_state.LISTE_CATEGORIES_COMPLETE.sort()
                            else:
                                st.error("Erreur ou doublon")
                                
                        st.session_state.input_new_cat = ""

                    with st.container(border=True, height=206):
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
                        st.text_input("Nom", placeholder="Ex: Essence...", label_visibility="collapsed", key="input_new_cat")

                        # Bouton de création
                        st.button("Créer la catégorie ✨", width='stretch', type="primary", on_click=valider_et_nettoyer)

                fragment_categorie()

                # 2. BOUTON D'ACTUALISATION (Hors fragment)
                # Ce bouton permet de voir les nouvelles catégories dans le tableau de droite
                st.button("🔄 Actualiser les catégories", width='stretch', help="Cliquez pour mettre à jour les listes du tableau après une création")

                st.markdown('<p style="font-weight:bold; color:#7f8c8d; margin-top:15px; margin-bottom:5px;">🔍 Filtres Tableau</p>', unsafe_allow_html=True)
                with st.container(border=True,height=403):
                    liste_g = ["Tous"] + st.session_state.groupes_liste
                    new_g = st.selectbox("Groupe", liste_g, index=liste_g.index(st.session_state.filter_g) if st.session_state.filter_g in liste_g else 0)
                    if new_g != st.session_state.filter_g:
                        st.session_state.filter_g = new_g
                        st.session_state.filter_c = "Tous"
                        relancer_avec_succes()

                    cps_filtre = ["Tous"] + (comptes_detectes if st.session_state.filter_g == "Tous" else [c for c,v in st.session_state.config_groupes.items() if v["Groupe"] == st.session_state.filter_g])
                    new_c = st.selectbox("Compte", cps_filtre, index=cps_filtre.index(st.session_state.filter_c) if st.session_state.filter_c in cps_filtre else 0)
                    if new_c != st.session_state.filter_c:
                        st.session_state.filter_c = new_c
                        relancer_avec_succes()

                    liste_a = ["Toutes"] + sorted(df_edit['Année'].unique().astype(str).tolist(), reverse=True)
                    st.selectbox("Année", liste_a, key="filter_a_select", on_change=lambda: setattr(st.session_state, 'filter_a', st.session_state.filter_a_select))
                    
                    liste_m = ["Tous"] + NOMS_MOIS
                    st.selectbox("Mois", liste_m, key="filter_m_select", on_change=lambda: setattr(st.session_state, 'filter_m', st.session_state.filter_m_select))

            # --- COLONNE 2 : AJOUT MANUEL & ACTIONS ---

            if "indices_reel" not in st.session_state:
                st.session_state.indices_reel = [0]

            with col_add:
                st.markdown('<p style="font-weight:bold; color:#3498db; margin-bottom:-10px;">➕ Saisie Opérations</p>', unsafe_allow_html=True)
                
                # Récupération des options
                options_comptes = list(st.session_state.config_groupes.keys()) if st.session_state.config_groupes else ["Défaut"]
                
                # Style CSS identique au précédent
                st.markdown("""
                    <style>
                    .stButton button { height: 48px !important; border-radius: 10px !important; font-weight: bold !important; font-size: 16px !important; }
                    .stTextInput input, .stNumberInput input, .stSelectbox div[role="button"] {
                        border-radius: 8px !important; background-color: rgba(52, 152, 219, 0.05) !important;
                    }
                    </style>
                """, unsafe_allow_html=True)

                with st.form("form_reel_multi"):
                    ops_reelles = []
                    
                    for idx in st.session_state.indices_reel:
                        with st.container():
                            # Ligne 1 : Description et Montant
                            c1, c2, c_eur = st.columns([2, 0.8, 0.2])
                            f_nom = c1.text_input("Description", key=f"r_n_{idx}", label_visibility="collapsed", placeholder="Description...")
                            f_mnt = c2.number_input("Montant", key=f"r_m_{idx}", label_visibility="collapsed", step=1.0, format="%.2f")
                            c_eur.markdown("<p style='margin-top:7px; font-weight:bold; color:gray;'>€</p>", unsafe_allow_html=True)
                            
                            # Ligne 2 : Compte, Catégorie, Date
                            c_cpte, c_cat, c_date = st.columns([1, 1, 1])
                            f_compte = c_cpte.selectbox("Compte", options_comptes, key=f"r_cp_{idx}", label_visibility="collapsed")
                            f_cat = c_cat.selectbox("Cat", LISTE_CATEGORIES_COMPLETE, key=f"r_cat_{idx}", label_visibility="collapsed")
                            f_date = c_date.date_input("Date", key=f"r_d_{idx}", label_visibility="collapsed")
                            
                            ops_reelles.append({
                            "Date": f_date.strftime('%Y-%m-%d'), # Sauvegarde en texte propre pour éviter l'erreur de format
                            "Nom": f_nom, 
                            "Montant": f_mnt,
                            "Categorie": f_cat, 
                            "Compte": f_compte,
                            "Mois": NOMS_MOIS[f_date.month - 1], 
                            "Année": f_date.year,
                            "User": st.session_state["username"]
                        })
                            st.markdown("<hr style='margin:10px 0; opacity:0.1;'>", unsafe_allow_html=True)

                    submit_reel = st.form_submit_button("Enregistrer les opérations 🚀", width='stretch', type="primary")

                # --- BOUTONS DE GESTION DES LIGNES ---
                cb1, cb2, cb3 = st.columns([1, 1, 1])
                
                if cb1.button("➕ Ligne", key="add_r", width='stretch'):
                    st.session_state.indices_reel.append(max(st.session_state.indices_reel) + 1)
                    relancer_avec_succes()

                if cb2.button("🗑️ Ligne", key="del_r", width='stretch'):
                    if len(st.session_state.indices_reel) > 1:
                        st.session_state.indices_reel.pop()
                        relancer_avec_succes()

                if cb3.button("🔄 Reset", key="reset_r", width='stretch'):
                    st.session_state.indices_reel = [0]
                    relancer_avec_succes()

                # --- LOGIQUE DE SAUVEGARDE ---
                if submit_reel:
                    valides = [o for o in ops_reelles if o["Nom"].strip() != "" and o["Montant"] != 0]
                    
                    if valides:
                        df_new_ops = pd.DataFrame(valides)
                        
                        # On s'assure que la colonne Date du DataFrame existant est aussi bien traitée
                        if not st.session_state.df.empty:
                            st.session_state.df['Date'] = pd.to_datetime(st.session_state.df['Date'], dayfirst=True, errors='coerce')
                        
                        # Fusion
                        df_total = pd.concat([st.session_state.df, df_new_ops], ignore_index=True)
                        
                        # Sauvegarde
                        try:
                            sauvegarder_donnees(df_total, st.session_state["username"])
                            st.cache_data.clear()
                            st.session_state.df = charger_donnees(st.session_state["username"])
                            
                            st.session_state.indices_reel = [0]
                            st.success(f"{len(valides)} opérations réelles ajoutées !")
                            time.sleep(1)
                            relancer_avec_succes()
                        except Exception as e:
                            st.error(f"Erreur lors de la sauvegarde : {e}")
                    else:
                        st.warning("Aucune opération valide à ajouter.")

                @st.dialog("Confirmation de suppression")
                def confirmer_suppression_dialog(nb_lignes, df_a_supprimer):
                    st.warning(f"⚠️ Vous êtes sur le point de supprimer **{nb_lignes}** lignes.")
                    st.write("Cette action modifiera définitivement vos données sur Google Sheets.")
                    st.info("Voulez-vous vraiment continuer ?")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Annuler", width='stretch'):
                            relancer_avec_succes()
                            
                    with col2:
                        if st.button("Oui, Supprimer", type="primary", width='stretch'):
                            # 1. On calcule le DataFrame restant
                            df_restant = st.session_state.df.drop(index=df_a_supprimer.index.tolist(), errors='ignore').reset_index(drop=True)
                            
                            # --- CORRECTION ICI : PRÉPARATION POUR GOOGLE SHEETS ---
                            try:
                                df_pour_gsheet = df_restant.copy()
                                
                                # On force la conversion en datetime (format flexible pour éviter l'erreur)
                                # dayfirst=True est crucial pour le format français 16/01
                                df_pour_gsheet['Date'] = pd.to_datetime(df_pour_gsheet['Date'], dayfirst=True, errors='coerce')
                                
                                # On transforme en texte format standard ISO pour Google Sheets
                                df_pour_gsheet['Date'] = df_pour_gsheet['Date'].dt.strftime('%Y-%m-%d')
                                
                                # 2. Sauvegarde et nettoyage
                                sauvegarder_donnees(df_pour_gsheet, st.session_state["username"])
                                
                                st.cache_data.clear()
                                st.session_state.df = df_restant # On garde les objets dates pour l'affichage interne
                                
                                st.success("Données supprimées !")
                                time.sleep(1)
                                relancer_avec_succes()
                                
                            except Exception as e:
                                st.error(f"Erreur lors de la sauvegarde : {e}")


                    
                    

                
                # 2. Dans votre interface principale (Colonne Sidebar / Actions)
                st.markdown('<p style="font-weight:bold; color:#ff4b4b; margin-top:15px; margin-bottom:5px;">⚠️ Supprimer les transactions en fonction des filtres choisis</p>', unsafe_allow_html=True)
                with st.container(border=True):
                    nb_s = len(df_f)
                    st.caption(f"Cible : {nb_s} lignes")

                    # Le bouton qui déclenche l'ouverture du Popup
                    if st.button("🗑️ Tout supprimer", width='stretch', type="secondary"):
                        if nb_s > 0:
                            # On appelle la fonction décorée par @st.dialog
                            confirmer_suppression_dialog(nb_s, df_f)
                        else:
                            st.warning("Aucune ligne à supprimer.")

                st.markdown('<p style="font-weight:bold; color:white; margin-top:15px; margin-bottom:5px;">💸 Plafonds & Budgets</p>', unsafe_allow_html=True)
                st.caption("Fixez vos limites mensuelles pour chaque catégorie et suivez vos économies en temps réel.")
                with st.container(border=True):

                
                    user_actuel = st.session_state["username"]
        
                    user = st.session_state["username"]
        
                    # Sélecteurs de contexte
                    c1, c2 = st.columns(2)
                    with c1:
                        m_cible = st.selectbox("Mois", ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"])
                    with c2:
                        liste_comptes = sorted(st.session_state.df['Compte'].unique().tolist())
                        c_cible = st.selectbox("Compte", liste_comptes)

                    # --- ZONE DE SAISIE COMPACTE ---
                    # On charge tous les budgets du mois/compte pour pré-remplir le chiffre
                    df_actuel = charger_budgets_complets(user, m_cible, c_cible)
                    
                    col_cat, col_montant, col_btn = st.columns([2, 1, 1])
                    
                    with col_cat:
                        cat_choisie = st.selectbox(
                            "Catégorie à définir", 
                            [c for c in LISTE_CATEGORIES_COMPLETE if c != "À catégoriser ❓"],
                            key="sel_cat_budget"
                        )
                    
                    with col_montant:
                        # On cherche si un montant existe déjà pour cette catégorie
                        valeur_existante = 0.0
                        if not df_actuel.empty:
                            match = df_actuel[df_actuel['Nom'] == cat_choisie]
                            if not match.empty:
                                valeur_existante = float(match['Somme'].iloc[0])
                        
                        # Le montant (number_input) se met à jour selon la catégorie choisie
                        nouveau_montant = st.number_input(
                            "Budget (€)", 
                            value=valeur_existante, 
                            step=10.0, 
                            key=f"input_{cat_choisie}_{m_cible}" # Clé dynamique pour forcer le rafraîchissement
                        )

                    with col_btn:
                        st.write(" ") # Espacement pour aligner le bouton
                        if st.button("Enregistrer ✅", width='stretch'):
                            if enregistrer_ligne_budget(user, m_cible, c_cible, cat_choisie, nouveau_montant):
                                st.toast(f"Budget {cat_choisie} mis à jour !", icon="✔️")
                                time.sleep(0.5)
                                relancer_avec_succes()

                


                    

            # --- COLONNE 3 : ÉDITION DU TABLEAU ---
            with col_main:
                # 1. INITIALISATION DES ÉTATS DE TRI
                if 'LISTE_CATEGORIES_COMPLETE' not in st.session_state:
        # On charge ici ta liste par défaut si vide
                    st.session_state.LISTE_CATEGORIES_COMPLETE = sorted(st.session_state.df['Categorie'].unique().tolist())

                if 'sort_by' not in st.session_state: st.session_state.sort_by = "Date"
                if 'sort_order' not in st.session_state: st.session_state.sort_order = "Descendant"

                if not df_f.empty:
                    # 1. On force la conversion en gérant les formats mixtes
                    # 'infer_datetime_format' aide Pandas à deviner le format ligne par ligne
                    df_f['Date'] = pd.to_datetime(df_f['Date'], dayfirst=True, errors='coerce')
                    
                    # 2. AU LIEU DE SUPPRIMER (dropna), on remplace les erreurs par la date du jour 
                    # ou une date fictive pour qu'elles restent visibles et éditables
                    mask_nan = df_f['Date'].isna()
                    if mask_nan.any():
                        # On met une date par défaut (ex: aujourd'hui) pour les dates illisibles
                        df_f.loc[mask_nan, 'Date'] = pd.Timestamp.now()
                    
                    # 3. Création de la version affichable
                    # On ajoute une sécurité : si c'est une date "récupérée", on met un indicateur
                    df_f['Date_Affiche'] = df_f.apply(
                        lambda r: r['Date'].strftime('%d/%m/%Y') if pd.notna(r['Date']) else "Date Error", 
                        axis=1
                    )



                    # --- LOGIQUE DE TRI ---
                    c_head1, c_head2, = st.columns([1.5, 1.5])
                    with c_head1:
                        st.markdown(f"### 📝 Édition ({len(df_f)})")
                    
                    with c_head2:
                        # On crée 2 petites colonnes pour les sélecteurs de tri
                        t1, t2 = st.columns(2)
                        with t1:
                            map_sort = {"Date": "Date", "Nom": "Nom", "Montant": "Montant", "Catégorie": "Categorie"}
                            sort_label = st.selectbox("Trier par", list(map_sort.keys()), index=0, label_visibility="collapsed")
                            st.session_state.sort_by = map_sort[sort_label]
                        with t2:
                            st.session_state.sort_order = st.selectbox("Ordre", ["Ascendant", "Descendant"], index=1, label_visibility="collapsed")
                   

                    
                    # Application du tri au DataFrame
                    ascending = True if st.session_state.sort_order == "Ascendant" else False
                    df_f = df_f.sort_values(by=st.session_state.sort_by, ascending=ascending)
                    
                else:
                    df_f['Date_Affiche'] = pd.Series(dtype='str')
                    st.markdown(f"### 📝 Édition (0)")

                # --- AFFICHAGE DU TABLEAU ---
                # En-têtes du tableau
                h_col1, h_col2, h_col3, h_col5, h_col4 = st.columns([2.5, 1.8, 1.5, 0.5,0.5])
                h_col1.caption("DÉTAILS")
                h_col2.caption("CATÉGORIE")
                h_col3.caption("MOIS") 
                h_col5.caption("Diviser")
                h_col4.caption("EFFACER")

                with st.container(height=665, border=True):
                    for idx, row in df_f.iterrows():
                        # Ton code existant pour la boucle (Logique de couleur, colonnes info/cat/mois/del)
                        # ... (copie ici ton code de boucle inchangé) ...
                        if "🔄" in str(row['Categorie']):
                            color_amount = "#9b59b6"
                        else:
                            color_amount = "#2ecc71" if row['Montant'] > 0 else "#ff4b4b"
                        
                        c_info, c_cat, c_mois,c_split, c_del = st.columns([2.5, 1.8, 1.5,0.5, 0.5])
                        
                        with c_info:
                            st.markdown(f'''
                                <div style="border-left:3px solid {color_amount}; padding-left:8px; line-height:1.2;">
                                    <div style="font-weight:bold; font-size:12px;">{row["Nom"]}</div>
                                    <div style="font-size:10px; color:gray;">{row["Date_Affiche"]} • {row["Compte"]}</div>
                                    <div style="font-weight:bold; color:{color_amount}; font-size:12px;">{row["Montant"]:.2f} €</div>
                                </div>
                            ''', unsafe_allow_html=True)
                        
                        with c_cat:
                            # --- PROTECTION DES CATÉGORIES MANUELLES ---
                            current_cat = row['Categorie']
                            nom_transac = row['Nom'] # On récupère le nom pour la comparaison
                            
                            # --- NOUVELLE FONCTIONNALITÉ : SUGGESTION PAR SIMILARITÉ ---
                            suggestion = None
                            nom_similaire = None
                            
                            # On ne cherche une suggestion que si la ligne n'est pas encore catégorisée
                            if pd.isna(current_cat) or current_cat in ["", "À catégoriser ❓"]:
                                # On cherche dans le DF global (st.session_state.df) des noms proches
                                noms_connus = st.session_state.df[st.session_state.df['Categorie'].notna()]['Nom'].unique().tolist()
                                from difflib import get_close_matches
                                matches = get_close_matches(nom_transac, noms_connus, n=1, cutoff=0.6)
                                
                                if matches:
                                    nom_similaire = matches[0]
                                    suggestion = st.session_state.df[st.session_state.df['Nom'] == nom_similaire]['Categorie'].iloc[0]

                            # --- LOGIQUE EXISTANTE DES OPTIONS ---
                            options_dynamiques = LISTE_CATEGORIES_COMPLETE.copy()
                            
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

                            # Affichage du Selectbox
                            nouvelle_cat = st.selectbox(
                                "C", 
                                options=options_dynamiques, 
                                index=idx_init, 
                                key=f"cat_{idx}", 
                                label_visibility="collapsed"
                            )
                            df_f.at[idx, 'Categorie'] = nouvelle_cat
    
                            # Petit indicateur visuel si une suggestion est appliquée
                            if suggestion and (pd.isna(current_cat) or current_cat in ["", "À catégoriser ❓"]):
                                st.caption(f"💡 Suggestion via : *{nom_similaire}*")
                        
                        with c_mois:
                            df_f.at[idx, 'Mois'] = st.selectbox("M", options=NOMS_MOIS, 
                                                                index=NOMS_MOIS.index(row['Mois']) if row['Mois'] in NOMS_MOIS else 0, 
                                                                key=f"mo_{idx}", label_visibility="collapsed")
                            

                        with c_split:
                            if st.button("✂️", key=f"split_{idx}", help="Diviser cette transaction en plusieurs parts"):
                                
                                @st.dialog(f"Diviser : {row['Nom']}")
                                def multi_split_dialog(index_origine, row_data):
                                    total_a_diviser = float(row_data['Montant'])
                                    st.write(f"Montant total à répartir : **{total_a_diviser}€**")
                                    
                                    # 1. Choisir en combien de parts diviser
                                    nb_parts = st.number_input("Nombre de parts", min_value=2, max_value=10, value=2)
                                    
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
                                                m_part = st.number_input(f"Montant {i+1}", value=reste, disabled=True, key=f"m_{i}")
                                            else:
                                                m_part = st.number_input(f"Montant {i+1}", value=round(total_a_diviser/nb_parts, 2), step=1.0, key=f"m_{i}")
                                                montant_cumule += m_part
                                        
                                        with col_c:
                                            c_part = st.selectbox(f"Catégorie {i+1}", options=LISTE_CATEGORIES_COMPLETE, key=f"c_{i}")
                                        
                                        nouvelles_parts.append({"montant": m_part, "categorie": c_part})

                                    st.divider()
                                    
                                    # 3. Validation et Sauvegarde
                                    if st.button("Confirmer la division ✅", width='stretch', type="primary"):
                                        df_temp = st.session_state.df.copy()
                                        
                                        # Création des nouvelles lignes basées sur l'originale
                                        nouvelles_lignes = []
                                        for part in nouvelles_parts:
                                            nouvelle_ligne = row_data.copy()
                                            nouvelle_ligne['Montant'] = part['montant']
                                            nouvelle_ligne['Categorie'] = part['categorie']
                                            # On peut optionnellement modifier le nom pour indiquer le split
                                            nouvelle_ligne['Nom'] = f"{row_data['Nom']} (Part)"
                                            nouvelles_lignes.append(nouvelle_ligne)
                                        
                                        # Mise à jour du DataFrame
                                        df_temp = df_temp.drop(index_origine)
                                        df_temp = pd.concat([df_temp, pd.DataFrame(nouvelles_lignes)], ignore_index=True)
                                        
                                        # Sauvegarde vers GSheets
                                        sauvegarder_donnees(df_temp, st.session_state.username)
                                        st.session_state.df = df_temp
                                        
                                        st.success(f"Transaction divisée en {nb_parts} !")
                                        time.sleep(1)
                                        relancer_avec_succes()

                                multi_split_dialog(idx, row)


                        
                        with c_del:
                            if st.button("", icon=":material/delete:", key=f"d_{idx}"):
                                # 1. Supprimer la ligne du DataFrame en session
                                st.session_state.df = st.session_state.df.drop(idx, errors='ignore').reset_index(drop=True)
                                
                                # 2. SAUVEGARDER IMMÉDIATEMENT dans le Google Sheet
                                sauvegarder_donnees(st.session_state.df, st.session_state["username"])
                                
                                # 3. Vider le cache pour forcer la lecture de la nouvelle version au prochain chargement
                                st.cache_data.clear()
                                
                                # 4. Petit message de confirmation (optionnel mais recommandé)
                                st.toast("Opération supprimée définitivement 🗑️")
                                
                                # 5. Rafraîchir l'affichage
                                relancer_avec_succes()
                        
                        st.markdown('<hr style="margin:4px 0; border:0; border-top:1px solid rgba(128,128,128,0.1);">', unsafe_allow_html=True)

            c_save3,c_save1, c_save2, = st.columns([3,1.5, 2])
            with c_save1:
                # Sauvegarde globale
                apprendre = st.checkbox("🧠 Mémoriser les catégories modifiées", value=False,help="Active l'apprentissage automatique : si vous renommez une catégorie, toutes les autres transactions portant exactement le même nom seront mises à jour avec cette nouvelle catégorie.")
            with c_save2:
               if st.button("💾 Sauvegarder les modifications", type="primary", width='stretch'):
                    user_actuel = st.session_state.get("username")
                    modifs = False
                    
                    for idx_s, row_s in df_f.iterrows():
                        if idx_s in st.session_state.df.index:
                            ancienne_cat = st.session_state.df.at[idx_s, 'Categorie']
                            
                            # Si la catégorie a changé
                            if row_s['Categorie'] != ancienne_cat:
                                nouvelle_cat = row_s['Categorie']
                                nom_operation = st.session_state.df.at[idx_s, 'Nom']
                                
                                # --- APPEL À TA FONCTION DE MÉMORISATION ---
                                if apprendre:
                                    # On met à jour l'onglet "Memoire" via ta fonction
                                    sauvegarder_apprentissage(nom_operation, nouvelle_cat, user_actuel)
                                    
                                    # On met aussi à jour TOUTES les lignes identiques dans le tableau actuel (UI)
                                    mask = st.session_state.df['Nom'] == nom_operation
                                    st.session_state.df.loc[mask, 'Categorie'] = nouvelle_cat
                                else:
                                    # Simple mise à jour de la ligne actuelle
                                    st.session_state.df.at[idx_s, 'Categorie'] = nouvelle_cat
                                
                                modifs = True
                            
                            # Mise à jour du mois (toujours spécifique à la ligne)
                            if row_s['Mois'] != st.session_state.df.at[idx_s, 'Mois']:
                                st.session_state.df.at[idx_s, 'Mois'] = row_s['Mois']
                                modifs = True

                    if modifs:
                        # --- SAUVEGARDE DU TABLEAU PRINCIPAL ---
                        df_a_sauver = st.session_state.df.copy()
                        try:
                            # Correction Date (format FR -> ISO)
                            df_a_sauver['Date'] = pd.to_datetime(df_a_sauver['Date'], dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
                            df_a_sauver['Date'] = df_a_sauver['Date'].fillna(pd.Timestamp.now().strftime('%Y-%m-%d'))

                            with st.spinner("Synchronisation avec Google Sheets..."):
                                sauvegarder_donnees(df_a_sauver, user_actuel)
                            
                            st.cache_data.clear()

                            # --- CHOIX DU MESSAGE SELON L'APPRENTISSAGE ---
                            if apprendre:
                                st.success("✅ Modifications et apprentissage mémorisés !") 
                            else:
                                st.success("✅ Modifications sauvegardées avec succès !") 

                            # Appel de ta fonction globale pour le toast + sleep + rerun
                            relancer_avec_succes()

                        except Exception as e:
                            st.error(f"Erreur sauvegarde principale : {e}")
                    else:
                        st.info("Aucune modification détectée.")

                    
                                        
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
                        comptes_transactions = st.session_state.df["Compte"].unique().tolist() if not st.session_state.df.empty else []
                        
                        # --- 2. On récupère les comptes de la config GSheets (Session State) ---
                        comptes_config = list(st.session_state.config_groupes.keys())
                        
                        # Fusion propre sans doublons
                        liste_finale = sorted(list(set(comptes_transactions + comptes_config)))
                        
                        c_nom = st.selectbox("Choisir le compte :", liste_finale)
                        
                    else:
                        c_nom = st.text_input("Nom du nouveau compte :", placeholder="Ex: Livret A")

                    stats_compte = st.session_state.df[st.session_state.df["Compte"] == c_nom]
                    
                    if not stats_compte.empty:
                        st.markdown("---")
                        c_st1, c_st2 = st.columns(2)
                        
                        # --- CORRECTION ICI ---
                        # On convertit en datetime pour pouvoir trouver le max et formater
                        dates_converties = pd.to_datetime(stats_compte["Date"], dayfirst=True, errors='coerce')
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
                                text = ""
                                for e in ['latin-1', 'utf-8', 'cp1252', 'utf-8-sig']:
                                    try: 
                                        text = raw.decode(e)
                                        break
                                    except: continue
                                
                                lines = [l.strip() for l in text.splitlines() if l.strip()]
                                h_idx, sep = None, ','
                                
                                # --- 2. DÉTECTION DE L'EN-TÊTE ---
                                # On cherche la ligne qui contient "Date" ET "Nom" ou "Montant"
                                for i, line in enumerate(lines[:20]):
                                    l_lower = line.lower()
                                    if "date" in l_lower and (any(m in l_lower for m in ["montant", "debit", "credit", "valeur"])):
                                        h_idx = i
                                        sep = ';' if line.count(';') > line.count(',') else ','
                                        break
                                
                                if h_idx is not None:
                                    # --- 3. LECTURE AVEC PARAMÈTRES FORCÉS ---
                                    df_n = pd.read_csv(
                                        io.StringIO("\n".join(lines[h_idx:])), 
                                        sep=sep, 
                                        engine='python',
                                        on_bad_lines='skip',
                                        skip_blank_lines=True
                                    )
                                    
                                    # Nettoyage radical des colonnes
                                    df_n.columns = [str(c).strip() for c in df_n.columns]
                                    df_n = df_n.loc[:, ~df_n.columns.duplicated()].copy()
                                    
                                    # --- 4. RENOMMAGE ---
                                    for std, syns in CORRESPONDANCE.items():
                                        for col in df_n.columns:
                                            if col in syns or col.lower() in [s.lower() for s in syns]: 
                                                df_n = df_n.rename(columns={col: std})
                                    
                                    # --- 5. VÉRIFICATION ET TRAITEMENT ---
                                    cols = df_n.columns.tolist()
                                    
                                    # On vérifie si on a les données minimales
                                    if "Date" in cols:
                                        # Conversion Date
                                        d_col = df_n["Date"].iloc[:, 0] if isinstance(df_n["Date"], pd.DataFrame) else df_n["Date"]
                                        df_n["Date_C"] = pd.to_datetime(d_col.astype(str), dayfirst=True, errors='coerce')
                                        df_n = df_n.dropna(subset=["Date_C"])
                                        
                                        # Détection Montant
                                        if "Debit" in cols and "Credit" in cols:
                                            c1 = df_n["Credit"].apply(clean_montant_physique).fillna(0)
                                            c2 = df_n["Debit"].apply(clean_montant_physique).fillna(0)
                                            df_n["M_Final"] = c1 - c2.abs()
                                        elif "Montant" in cols:
                                            df_n["M_Final"] = df_n["Montant"].apply(clean_montant_physique)
                                        else:
                                            st.error(f"Colonnes trouvées : {cols}. Vérifiez votre fichier CSV.")
                                            st.stop()

                                        # Détection Nom
                                        n_col = "Nom" if "Nom" in cols else (cols[1] if len(cols) > 1 else cols[0])
                                        

                                        # --- 6. CRÉATION DU DF FINAL ---
                                        df_res = pd.DataFrame({
                                            "Date": df_n["Date_C"], 
                                            "Nom": df_n[n_col].astype(str).apply(simplifier_nom_definitif),
                                            "Montant": df_n["M_Final"], 
                                            "Compte": [c_nom] * len(df_n)
                                        })

        

                                        # --- MODIFICATION ICI : On utilise df_n pour avoir accès à TOUTES les colonnes ---
                                        df_res["Categorie"] = df_n.apply(
                                            lambda row: categoriser(row[n_col], row["M_Final"], c_nom, row), 
                                            axis=1
                                        )

                                        df_res["Mois"] = df_res["Date"].dt.month.map(lambda x: NOMS_MOIS[int(x)-1])
                                        df_res["Année"] = df_res["Date"].dt.year
                                        
                                        # --- SAUVEGARDE ET SYNCHRONISATION ---

                                        # 1. On récupère les données déjà présentes dans le Google Sheet
                                        try:
                                            df_existant = charger_donnees(st.session_state["username"])
                                        except:
                                            df_existant = pd.DataFrame()

                                        # 2. On fusionne l'existant avec les nouvelles transactions
                                        if not df_existant.empty:
                                            # On met les nouvelles lignes à la suite des anciennes
                                            df_final = pd.concat([df_existant, df_res], ignore_index=True)
                                        else:
                                            df_final = df_res

                                        # --- 3. SUPPRESSION DES DOUBLONS ---
                                        df_final = df_final.drop_duplicates(subset=['Date', 'Nom', 'Montant', 'Compte'], keep='first')

                                        # --- 4. PRÉPARATION POUR GOOGLE SHEETS (Correction de l'erreur) ---
                                        try:
                                            df_pour_gsheet = df_final.copy()
                                            
                                            # Sécurité : On force la colonne en datetime avant d'extraire le texte
                                            df_pour_gsheet['Date'] = pd.to_datetime(df_pour_gsheet['Date'], errors='coerce')
                                            
                                            # On retire les lignes où la date n'a pas pu être convertie (NaT)
                                            df_pour_gsheet = df_pour_gsheet.dropna(subset=['Date'])
                                            
                                            # Maintenant on peut utiliser .dt sans risque d'AttributeError
                                            df_pour_gsheet['Date'] = df_pour_gsheet['Date'].dt.strftime('%Y-%m-%d')
                                            
                                            # --- 5. SAUVEGARDE ET SYNCHRONISATION ---
                                            sauvegarder_donnees(df_pour_gsheet, st.session_state["username"])
                                            
                                            # On met à jour l'app avec les données propres
                                            st.session_state.df = df_final
                                            st.toast("✅ Données synchronisées avec succès !", icon="🚀")
                                            
                                            # Stats pour le résumé
                                            st.session_state.dernier_import_stats = {
                                                "nb": len(df_res),
                                                "dep": df_res[df_res['Montant'] < 0]['Montant'].sum(),
                                                "rev": df_res[df_res['Montant'] > 0]['Montant'].sum(),
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
                                    st.error("Impossible de trouver la ligne d'en-tête (Date, Montant...).")

                        except Exception as e:
                            st.error(f"❌ Erreur critique : {e}")


                # --- AFFICHAGE DU COMPTE-RENDU (Permanent après import) ---
                if st.session_state.dernier_import_stats:
                    stats = st.session_state.dernier_import_stats
                    
                    st.markdown("---")
                    st.markdown(f"### 📊 Résumé du dernier import ({stats['date']})")
                    
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns(4)
                        
                        c1.metric("Compte cible", stats['compte'])
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
                        2. Allez dans la section **'Comptes'** puis **'Mes opérations'**.
                        3. Cliquez sur le bouton **'Exporter'** (souvent en haut à droite).
                        4. Sélectionnez le format **CSV** (parfois appelé 'Format tableur').
                        5. Validez pour lancer le téléchargement.
                        """)

                    st.caption("⚠️ Assurez-vous que le fichier contient bien les colonnes Date, Nom/Libellé et Montant.")


                    
    elif selected == "Tricount":
        st.header("🤝 Tricount")

        # 1. RÉCUPÉRATION DES GROUPES EXISTANTS
        df_tri = charger_tricount_gsheet(st.session_state["username"])
        
        groupes_existants = []
        if not df_tri.empty and 'Groupe' in df_tri.columns:
            groupes_existants = sorted(df_tri['Groupe'].unique().tolist())
        
        options_groupes = ["-- Choisir un groupe --"] + groupes_existants

        # 2. SÉLECTION OU CRÉATION DE GROUPE
        col_g1, col_g2 = st.columns([2, 1])
        
        with col_g1:
            groupe_choisi = st.selectbox("📂 Sélectionner votre groupe", options_groupes)

        # Déplacement de la fonction de rafraîchissement (logique pure)
        def rafraichir_membres(df, groupe):
            membres = set()
            if not df.empty and groupe != "-- Choisir un groupe --":
                df_g = df[df['Groupe'] == groupe]
                if not df_g.empty:
                    membres.update(df_g['Payé_Par'].unique())
                    for pq in df_g['Pour_Qui'].dropna():
                        for item in str(pq).split(','):
                            if ':' in item:
                                nom = item.split(':')[0]
                                membres.update([nom])
            # On retire les noms techniques
            return [m for m in membres if m not in ["Système", st.session_state["username"] + "_init"]]

        with col_g2:
            st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
            @st.dialog("➕ Créer un nouveau groupe")
            def dialogue_creation_groupe(df_tri):
                nom_nouveau = st.text_input("Nom du voyage ou du projet")
                if st.button("Confirmer la création"):
                    if nom_nouveau:
                        data_init = {
                            "Date": datetime.now().strftime("%d/%m/%Y"),
                            "Libellé": "Initialisation du groupe",
                            "Payé_Par": "Système",
                            "Pour_Qui": "Système:0",
                            "Montant": 0.0,
                            "Groupe": nom_nouveau,
                            "Utilisateur": st.session_state["username"]
                        }
                        if sauvegarder_transaction_tricount(df_tri, data_init):
                            st.success(f"Groupe '{nom_nouveau}' créé !")
                            st.cache_data.clear()
                            st.rerun()

            if st.button("➕ Nouveau Groupe", use_container_width=True):
                dialogue_creation_groupe(df_tri)


            @st.dialog("✏️ Renommer le groupe")
            def dialogue_renommer_groupe(df_tri, ancien_nom):
                nouveau_nom = st.text_input("Nouveau nom du groupe", value=ancien_nom)
                st.info(f"Toutes les dépenses de '{ancien_nom}' seront transférées vers '{nouveau_nom}'.")
                
                if st.button("Confirmer le changement", use_container_width=True):
                    if nouveau_nom and nouveau_nom != ancien_nom:
                        # On remplace l'ancien nom par le nouveau dans tout le DataFrame
                        # Uniquement pour l'utilisateur actuel
                        mask = (df_tri['Groupe'] == ancien_nom) & (df_tri['Utilisateur'] == st.session_state["username"])
                        df_tri.loc[mask, 'Groupe'] = nouveau_nom
                        
                        # Mise à jour vers Google Sheets
                        conn = st.connection("gsheets", type=GSheetsConnection)
                        try:
                            conn.update(worksheet="Tricount", data=df_tri)
                            st.success(f"Groupe renommé en '{nouveau_nom}' !")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erreur lors de la mise à jour : {e}")
                    else:
                        st.warning("Veuillez saisir un nom différent.")

            
                

        # 3. LOGIQUE D'AFFICHAGE CONDITIONNELLE
        if groupe_choisi == "-- Choisir un groupe --":
            st.info("👋 Bienvenue ! Veuillez sélectionner un groupe existant ou en créer un nouveau pour commencer.")
            
        else:
            groupe_actuel = groupe_choisi
        
            if "participants" not in st.session_state or st.session_state.get('last_group') != groupe_actuel:
                st.session_state.participants = rafraichir_membres(df_tri, groupe_actuel)
                st.session_state.last_group = groupe_actuel

            # 2. NETTOYAGE (Seulement maintenant qu'on est sûr que la liste existe)
            if "Système" in st.session_state.participants:
                st.session_state.participants.remove("Système")

            @st.dialog("⚠️ Supprimer le groupe")
            def dialogue_suppression_groupe(df_tri, groupe_a_supprimer):
                st.warning(f"Es-tu sûr de vouloir supprimer le groupe **{groupe_a_supprimer}** ?")
                st.info("Cette action supprimera toutes les dépenses liées à ce groupe dans le Google Sheet.")
                
                if st.button("OUI, TOUT SUPPRIMER", use_container_width=True):
                    # Filtrage : on garde tout sauf ce groupe précis pour cet utilisateur
                    df_nettoye = df_tri[~((df_tri['Groupe'] == groupe_a_supprimer) & (df_tri['Utilisateur'] == st.session_state["username"]))]
                    
                    
                    try:
                        conn.update(worksheet="Tricount", data=df_nettoye)
                        st.success("Groupe supprimé !")
                        st.cache_data.clear()
                        # On réinitialise la sélection pour ne pas rester sur un groupe qui n'existe plus
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur : {e}")

            c_del, c_edit = st.columns(2)
    
            with c_del:
                if st.button("🗑️ Supprimer", use_container_width=True):
                    dialogue_suppression_groupe(df_tri, groupe_choisi)
                    
            with c_edit:
                if st.button("✏️ Renommer", use_container_width=True):
                    dialogue_renommer_groupe(df_tri, groupe_choisi)

            # --- MISE EN PAGE SUR 4 COLONNES ---
            col_membres, col_saisie, col_bilan, col_histo = st.columns([0.8, 1, 1.8, 1.8], gap="medium")
            

        
            # --- COLONNE 1 : GESTION DES MEMBRES ---
            with col_membres:
                st.markdown("### 👥 Membres")
                new_p = st.text_input("Nom du membre", key="input_new_p", label_visibility="collapsed", placeholder="Ex: Alex, Marie...")
                
                if st.button("➕ Ajouter au groupe", use_container_width=True):
                    if new_p:
                        # Nettoyage des espaces
                        nom = new_p.strip()
                        if nom not in st.session_state.participants:
                            st.session_state.participants.append(nom)
                            st.rerun()
                        else:
                            st.warning("Ce membre est déjà dans la liste.")
                
                st.markdown("---")
                if not st.session_state.participants:
                    st.info("☝️ Ajoutez des membres pour commencer.")
                else:
                    for i, p in enumerate(st.session_state.participants):
                        c_name, c_del = st.columns([4, 1])
                        c_name.write(f"**{p}**")
                        if c_del.button("❌", key=f"del_p_{i}"):
                            # On vérifie si le membre a déjà des dettes avant de supprimer
                            st.session_state.participants.remove(p)
                            st.rerun()

            # --- COLONNE 2 : FORMULAIRE DE SAISIE ---
            with col_saisie:
                st.markdown("### ➕ Nouvelle dépense")
                
                with st.container(border=True):
                    libelle = st.text_input("Libellé", placeholder="Restaurant, Courses...")
                    montant_total = st.number_input("Montant Total (€)", min_value=0.0, step=0.01)
                    payeur = st.selectbox("Qui a payé ?", st.session_state.participants)
                    
                    st.markdown("**Qui consomme ?**")
                    p_concernes = st.multiselect(
                        "Sélectionner les participants", 
                        st.session_state.participants,
                        default=st.session_state.participants,
                        key="select_p"
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
                    
                    if nb_p > 0:
                        cols = st.columns(2)
                        # La valeur par défaut 'value' utilise maintenant la part équitable calculée
                        for idx, p in enumerate(p_concernes):
                            with cols[idx % 2]:
                                parts_saisies[p] = st.number_input(
                                    f"Part de {p}", 
                                    min_value=0.0, 
                                    value=montant_total / nb_p if nb_p > 0 else 0.0,
                                    step=0.01, 
                                    key=f"input_part_{p}" 
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
                    if st.button("Enregistrer la dépense 💾", use_container_width=True, type="primary"):
                        if montant_total <= 0 or nb_p == 0 or abs(diff) > 0.01:
                            st.error("Veuillez vérifier le montant et la répartition.")
                        else:
                            repartition_str = ",".join([f"{p}:{val}" for p, val in parts_saisies.items()])
                            
                            nouvelle_depense = {
                                "Date": datetime.now().strftime("%d/%m/%Y"),
                                "Libellé": libelle,
                                "Payé_Par": payeur,
                                "Pour_Qui": repartition_str,
                                "Montant": montant_total,
                                "Groupe": groupe_actuel,
                                "Utilisateur": st.session_state["username"]
                            }
                            
                            if sauvegarder_transaction_tricount(df_tri, nouvelle_depense):
                                st.success("Dépense ajoutée !")
                                st.cache_data.clear()
                                st.rerun()

            # --- COLONNE 3 : BILAN ET REMBOURSEMENTS ---
            with col_bilan:
                st.markdown("### 💵 BILAN DES REMBOURSEMENTS")

                if not df_tri.empty:
                    df_groupe = df_tri[df_tri['Groupe'] == groupe_actuel]
                    participants = st.session_state.participants
                    
                    # 1. CALCUL DES DETTES BRUTES
                    dettes_brutes = {p1: {p2: 0.0 for p2 in participants} for p1 in participants}
                    for _, row in df_groupe.iterrows():
                        payeur = str(row['Payé_Par']).strip()
                        if payeur == "Système": continue
                        parts = str(row['Pour_Qui']).split(',')
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

                                # Création du container individuel
                                with st.container(border=True):
                                    # En-tête du container : Nom et Badge de solde
                                    c1, c2 = st.columns([1.5, 1])
                                    c1.markdown(f"#### 👤 {p}")
                                    
                                    if solde_final > 0:
                                        c2.markdown(f"<div style='text-align:right; color:#00D166; font-weight:bold;'>+{solde_final:.2f}€</div>", unsafe_allow_html=True)
                                    elif solde_final < 0:
                                        c2.markdown(f"<div style='text-align:right; color:#FF4B4B; font-weight:bold;'>{solde_final:.2f}€</div>", unsafe_allow_html=True)
                                    else:
                                        c2.markdown(f"<div style='text-align:right; color:gray;'>Quitte</div>", unsafe_allow_html=True)


                                    # Détail des mouvements
                                    if a_donner:
                                        for t in a_donner:
                                            st.markdown(f"🔴 **Donne** {t['montant']:.2f}€ à {t['a']}")
                                    
                                    if a_recevoir:
                                        for t in a_recevoir:
                                            st.markdown(f"🟢 **Reçoit** {t['montant']:.2f}€ de {t['de']}")
                                    
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
                                            key=f"pdf_btn_{p}",
                                            use_container_width=True
                                        )

                        # --- ACTION GLOBALE TOUT EN BAS ---
                        pdf_global = generer_pdf_tricount(f"Global - {groupe_actuel}", df_groupe, transferts_finaux, df_groupe['Montant'].sum())
                        st.download_button(
                            label="📥 TÉLÉCHARGER LE BILAN COMPLET DU GROUPE (PDF)",
                            data=bytes(pdf_global),
                            file_name=f"Bilan_Global_{groupe_actuel}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )

                    else:
                        st.success("✨ Tout le monde est parfaitement quitte !")


            @st.dialog("✏️ Modifier la transaction")
            def modifier_transaction(index, row, df_global):
                st.markdown(f"**Groupe :** {row['Groupe']}")
                
                # 1. Champs de base
                new_libelle = st.text_input("Libellé", value=row['Libellé'])
                new_montant = st.number_input("Montant Total (€)", value=float(row['Montant']), min_value=0.01)
                new_payeur = st.selectbox("Qui a payé ?", st.session_state.participants, 
                                        index=st.session_state.participants.index(row['Payé_Par']) if row['Payé_Par'] in st.session_state.participants else 0)

                st.divider()
                st.markdown("💰 **Ajuster les parts individuelles :**")

                # 2. Décodage des parts actuelles pour l'affichage
                # On crée un dictionnaire des parts existantes { Nom: Montant }
                parts_actuelles = {}
                for item in str(row['Pour_Qui']).split(','):
                    if ':' in item:
                        n, v = item.split(':')
                        parts_actuelles[n] = float(v)

                # 3. Création des champs de saisie pour chaque participant
                new_parts = {}
                for p in st.session_state.participants:
                    # On pré-remplit avec la valeur actuelle (ou 0 si la personne n'était pas incluse)
                    valeur_defaut = parts_actuelles.get(p, 0.0)
                    new_parts[p] = st.number_input(f"Part de {p}", min_value=0.0, value=valeur_defaut, key=f"edit_part_{p}")

                total_parts = sum(new_parts.values())
                
                # 4. Validation et Enregistrement
                if total_parts != new_montant:
                    st.warning(f"La somme des parts ({total_parts:.2f}€) doit être égale au total ({new_montant:.2f}€)")
                
                if st.button("Enregistrer les modifications", use_container_width=True, disabled=(abs(total_parts - new_montant) > 0.01)):
                    # Encodage de la nouvelle répartition
                    repartition_str = ",".join([f"{p}:{val}" for p, val in new_parts.items() if val > 0])
                    
                    # Mise à jour du DataFrame
                    df_global.at[index, 'Libellé'] = new_libelle
                    df_global.at[index, 'Montant'] = new_montant
                    df_global.at[index, 'Payé_Par'] = new_payeur
                    df_global.at[index, 'Pour_Qui'] = repartition_str
                    
                    # Sauvegarde vers Google Sheets
                    conn = st.connection("gsheets", type=GSheetsConnection)
                    try:
                        conn.update(worksheet="Tricount", data=df_global)
                        st.cache_data.clear()
                        st.success("C'est à jour ! 🚀")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur lors de la mise à jour : {e}")

            # --- COLONNE 4 : HISTORIQUE ET MODIFICATIONS ---
            with col_histo:
                st.markdown("### 📜 Historique")
                
                if not df_tri.empty:
                    # Filtrage par groupe actuel ET exclusion de l'initialisation système
                    # On ne garde que les vraies dépenses (Montant > 0 et pas payé par Système)
                    df_groupe_h = df_tri[
                        (df_tri['Groupe'] == groupe_actuel) & 
                        (df_tri['Payé_Par'] != "Système") & 
                        (df_tri['Montant'] > 0)
                    ]
                    
                    if not df_groupe_h.empty:
                        # --- CALCUL DU TOTAL ---
                        total_groupe = df_groupe_h['Montant'].sum()
                        
                        # Affichage du total
                        st.metric(label=f"Total des dépenses : {groupe_actuel}", value=f"{total_groupe:.2f} €")

                        # Liste des transactions (scrollable)
                        with st.container(height=700):
                            # Tri pour avoir les plus récentes en haut
                            for idx, row in df_groupe_h.sort_index(ascending=False).iterrows():
                                with st.container(border=True):
                                    c1, c2 = st.columns([3, 1])
                                    with c1:
                                        st.markdown(f"**{row['Libellé']}**")
                                        st.caption(f"📅 {row['Date']} • Par **{row['Payé_Par']}**")
                                        st.markdown(f"💰 **{row['Montant']:.2f}€**")
                                    with c2:
                                        if st.button("🗑️", key=f"del_{idx}"):
                                            # On passe : le DF, l'index, et TA connexion 'conn'
                                            if supprimer_transaction_tricount(df_tri, idx, conn):
                                                # On vide le cache pour forcer Streamlit à relire le Sheet modifié
                                                st.cache_data.clear()
                                                st.toast("✅ Transaction supprimée avec succès")
                                                st.rerun()
                                        
                                        # Bouton édition
                                        if st.button("✏️", key=f"edit_{idx}"):
                                            modifier_transaction(idx, row, df_tri) 
                                            pass 
                    else:
                        st.info("Aucune dépense enregistrée.")
                else:
                    st.write("Le sheet est vide.")