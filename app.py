# app.py
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g, flash
from collections import defaultdict
import os
from datetime import datetime
import random
from flask import Flask, render_template, request, redirect, url_for, g, flash, make_response # <--- VÉRIFIEZ CETTE LIGNE
from reportlab.lib.pagesizes import letter, A4 # AJOUTÉ
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle # AJOUTÉ
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle # AJOUTÉ
from reportlab.lib import colors # AJOUTÉ
from reportlab.lib.units import inch, cm # AJOUTÉ
import io # AJOUTÉ

app = Flask(__name__)
app.secret_key = os.urandom(24)

DATABASE_FOLDER = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(DATABASE_FOLDER, 'database.db')

DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
TIMES = ["08h30", "10h30", "13h30", "14h00"]

EXPECTED_TEACHERS = sorted([
    "AMRANE", "ARFFAA", "BAH", "BENMAKHLOUF", "CATTEZ",
    "DUCAMPS", "JACQUELOT", "LEROY", "NGUER", "SAGADEVIN"
])

# AJOUTÉ: Liste pour les options du menu déroulant, incluant "Autre..."
SELECT_OPTIONS_TEACHERS = EXPECTED_TEACHERS + ["Autre..."]


# --- Fonctions Base de Données ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('init_db.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()
    print("Base de données initialisée.")

@app.cli.command('init-db')
def init_db_command():
    init_db()
    print('Initialized the database.')

# --- Fonctions Utilitaires ---
def calculate_votes_and_majority():
    db = get_db()
    submissions_raw = db.execute('SELECT * FROM submissions ORDER BY submitted_at DESC').fetchall()
    votes_per_slot = defaultdict(lambda: defaultdict(int)) # Utilisation de defaultdict pour simplifier
    comments_list = []
    teachers_who_voted_set = set() # Enseignants qui ont effectivement soumis un vote

    for day_init in DAYS:
        for time_init in TIMES:
            votes_per_slot[day_init][time_init] = 0 # S'assurer que tous les slots sont initialisés

    for sub in submissions_raw:
        teacher_name_from_db = sub['teacher_name']
        votes_per_slot[sub['day_of_week']][sub['time_slot']] += 1
        if sub['comment'] and sub['comment'].strip():
            comments_list.append({
                'teacher': sub['teacher_name'],
                'day': sub['day_of_week'],
                'time': sub['time_slot'],
                'comment_text': sub['comment']
            })
        teachers_who_voted_set.add(teacher_name_from_db)

    flat_slots = []
    for day_flat, times_dict_flat in votes_per_slot.items():
        for time_flat, count_flat in times_dict_flat.items():
            flat_slots.append(((day_flat, time_flat), count_flat))

    popular_slots_sorted = sorted(flat_slots, key=lambda x: x[1], reverse=True)
    popular_slots_display = [item for item in popular_slots_sorted if item[1] > 0]

    majority_slot_info = None
    if popular_slots_sorted and popular_slots_sorted[0][1] > 0:
        max_votes = popular_slots_sorted[0][1]
        top_voted_slots = [
            {"day": slot_tuple[0], "time": slot_tuple[1], "votes": count}
            for slot_tuple, count in popular_slots_sorted if count == max_votes
        ]
        if top_voted_slots:
            majority_slot_info = {
                "slots": top_voted_slots,
                "votes": max_votes,
                "is_tie": len(top_voted_slots) > 1
            }
    
    days_with_votes = set()
    for day_dv, times_dict_dv in votes_per_slot.items():
        if any(c > 0 for c in times_dict_dv.values()):
            days_with_votes.add(day_dv)
    days_without_any_selection = [d for d in DAYS if d not in days_with_votes]

    # La vérification de "tous ont voté" se base sur EXPECTED_TEACHERS
    # et sur les noms normalisés (ici, on assume que les noms dans la DB correspondent à EXPECTED_TEACHERS)
    voted_from_expected_list_set = teachers_who_voted_set.intersection(set(EXPECTED_TEACHERS))
    all_expected_voted = set(EXPECTED_TEACHERS).issubset(teachers_who_voted_set)
    missing_teachers = sorted(list(set(EXPECTED_TEACHERS) - teachers_who_voted_set))

    return {
        "submissions_raw": submissions_raw, "votes_per_slot": votes_per_slot,
        "comments_list": comments_list, 
        "all_teacher_names": sorted(list(teachers_who_voted_set)), # Tous ceux qui ont voté
        "voted_from_expected_list": sorted(list(voted_from_expected_list_set)), # Ceux de la liste principale qui ont voté
        "popular_slots_display": popular_slots_display, "majority_slot_info": majority_slot_info,
        "days_without_any_selection": days_without_any_selection,
        "all_expected_voted": all_expected_voted, # Booléen: tous les attendus ont-ils voté?
        "missing_teachers": missing_teachers,       # Liste des attendus qui n'ont pas voté
        "expected_teacher_count": len(EXPECTED_TEACHERS)
    }
    


def get_final_choice_from_db():
    db = get_db()
    choice_row = db.execute('SELECT * FROM final_choice ORDER BY chosen_at DESC LIMIT 1').fetchone()
    return choice_row

# --- Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    db = get_db()
    final_choice_db = get_final_choice_from_db()
    # Calculer les données de vote une seule fois au début de la fonction
    vote_data = calculate_votes_and_majority()

    if request.method == 'POST':
        if final_choice_db:
            flash("Un choix final a déjà été fait. Les votes sont clos.", "warning")
            return redirect(url_for('index'))

        selected_teacher_option = request.form.get('teacher_name_select', '').strip()
        other_teacher_name_input = request.form.get('other_teacher_name', '').strip()
        
        final_teacher_name = ""
        if selected_teacher_option == "Autre...":
            final_teacher_name = other_teacher_name_input
        elif selected_teacher_option:
            final_teacher_name = selected_teacher_option

        if not final_teacher_name:
            flash("Le nom de l'enseignant est obligatoire.", "danger")
            # On utilise vote_data déjà calculé
            return render_template('index.html', days=DAYS, times=TIMES,
                                   current_year=datetime.now().year, final_choice_db=final_choice_db,
                                   select_options_teachers=SELECT_OPTIONS_TEACHERS, **vote_data)

        # VÉRIFICATION : L'ENSEIGNANT A-T-IL DÉJÀ VOTÉ ?
        existing_vote_check = db.execute('SELECT 1 FROM submissions WHERE teacher_name = ? LIMIT 1', 
                                         (final_teacher_name,)).fetchone()
        if existing_vote_check:
            flash(f"{final_teacher_name}, vous avez déjà soumis vos disponibilités. Pour les modifier ou voter à nouveau, veuillez d'abord supprimer vos votes actuels en utilisant le formulaire de suppression.", "warning")
            # On utilise vote_data déjà calculé
            return render_template('index.html', days=DAYS, times=TIMES,
                                   current_year=datetime.now().year, final_choice_db=final_choice_db,
                                   select_options_teachers=SELECT_OPTIONS_TEACHERS, **vote_data)

        # Si l'enseignant n'a pas encore voté, on procède à l'insertion.
        # La ligne db.execute('DELETE FROM submissions WHERE teacher_name = ?', (final_teacher_name,))
        # n'est plus nécessaire ici car on empêche de revoter. Elle est gérée par /delete_my_votes

        has_made_a_choice = False
        for day_form in DAYS:
            selected_slot = request.form.get(f'slot_{day_form}')
            comment = request.form.get(f'comment_{day_form}', '').strip()
            if selected_slot: # Si un créneau (pas "Indisponible") est sélectionné
                db.execute(
                    'INSERT INTO submissions (teacher_name, day_of_week, time_slot, comment) VALUES (?, ?, ?, ?)',
                    (final_teacher_name, day_form, selected_slot, comment)
                )
                has_made_a_choice = True
        
        if has_made_a_choice:
            flash(f"Merci {final_teacher_name}, vos choix ont été enregistrés.", "success")
        else:
            flash(f"{final_teacher_name}, vous n'avez sélectionné aucun créneau. Si ce n'était pas votre intention, veuillez supprimer cette soumission (vide) et recommencer.", "info")
        
        db.commit()
        return redirect(url_for('index'))

    # Méthode GET (vote_data est déjà calculé en haut)
    return render_template(
        'index.html',
        days=DAYS, times=TIMES,
        current_year=datetime.now().year,
        final_choice_db=final_choice_db,
        select_options_teachers=SELECT_OPTIONS_TEACHERS,
        **vote_data # Passe toutes les clés du dictionnaire vote_data
    )
@app.route('/delete_my_votes', methods=['POST'])
def delete_my_votes():
    db = get_db()
    final_choice_db = get_final_choice_from_db()
    if final_choice_db:
        flash("Un choix final a déjà été fait. Il n'est plus possible de supprimer des votes.", "warning")
        return redirect(url_for('index'))

    # MODIFIÉ: Logique pour gérer l'option "Autre..."
    selected_teacher_option_del = request.form.get('teacher_name_to_delete_select', '').strip()
    other_teacher_name_del_input = request.form.get('other_teacher_name_delete', '').strip()

    teacher_name_to_delete = ""
    if selected_teacher_option_del == "Autre...":
        teacher_name_to_delete = other_teacher_name_del_input
    elif selected_teacher_option_del:
        teacher_name_to_delete = selected_teacher_option_del

    if not teacher_name_to_delete:
        flash("Veuillez sélectionner un nom dans la liste ou saisir un nom (si 'Autre...') pour la suppression.", "danger")
        return redirect(url_for('index'))
    
    # La validation `if teacher_name_to_delete not in EXPECTED_TEACHERS:` est enlevée.

    existing_votes = db.execute('SELECT 1 FROM submissions WHERE teacher_name = ?', (teacher_name_to_delete,)).fetchone()
    if not existing_votes:
        flash(f"Aucun vote trouvé pour {teacher_name_to_delete}.", "info")
        return redirect(url_for('index'))

    db.execute('DELETE FROM submissions WHERE teacher_name = ?', (teacher_name_to_delete,))
    db.commit()
    flash(f"Tous les votes de {teacher_name_to_delete} ont été supprimés.", "success")
    return redirect(url_for('index'))


@app.route('/resolve_tie', methods=['POST'])
def resolve_tie():
    db = get_db()
    final_choice_db = get_final_choice_from_db()
    if final_choice_db:
        flash("Un choix final a déjà été fait.", "warning")
        return redirect(url_for('index'))

    vote_data = calculate_votes_and_majority()
    majority_info = vote_data.get("majority_slot_info")
    all_expected_voted = vote_data.get("all_expected_voted") # Ceci est toujours basé sur EXPECTED_TEACHERS

    if not all_expected_voted:
        flash("Le départage ne peut avoir lieu que si tous les enseignants de la liste principale ont voté.", "danger") # Message clarifié
        return redirect(url_for('index'))

    if not (majority_info and majority_info["is_tie"] and majority_info["slots"]):
        flash("Il n'y a pas d'égalité à départager ou aucun vote n'a été soumis par les enseignants principaux.", "info") # Message clarifié
        return redirect(url_for('index'))

    chosen_slot = random.choice(majority_info["slots"])
    db.execute('DELETE FROM final_choice')
    db.execute(
        'INSERT INTO final_choice (day_of_week, time_slot, votes, is_tie_breaker) VALUES (?, ?, ?, ?)',
        (chosen_slot["day"], chosen_slot["time"], chosen_slot["votes"], True)
    )
    db.commit()
    flash(f"Égalité résolue ! Le créneau retenu est : {chosen_slot['day']} à {chosen_slot['time']}.", "success")
    return redirect(url_for('index'))

@app.route('/confirm_majority_choice', methods=['POST'])
def confirm_majority_choice():
    db = get_db()
    final_choice_db = get_final_choice_from_db()
    if final_choice_db:
        flash("Un choix final a déjà été fait.", "warning")
        return redirect(url_for('index'))

    vote_data = calculate_votes_and_majority()
    majority_info = vote_data.get("majority_slot_info")
    all_expected_voted = vote_data.get("all_expected_voted") # Ceci est toujours basé sur EXPECTED_TEACHERS

    if not all_expected_voted:
        flash("La confirmation du choix ne peut avoir lieu que si tous les enseignants de la liste principale ont voté.", "danger") # Message clarifié
        return redirect(url_for('index'))

    if not (majority_info and not majority_info["is_tie"] and majority_info["slots"]):
        flash("Il n'y a pas de choix majoritaire clair à confirmer basé sur les votes des enseignants principaux, ou aucun vote.", "info") # Message clarifié
        return redirect(url_for('index'))
    
    winning_slot = majority_info["slots"][0]
    db.execute('DELETE FROM final_choice')
    db.execute(
        'INSERT INTO final_choice (day_of_week, time_slot, votes, is_tie_breaker) VALUES (?, ?, ?, ?)',
        (winning_slot["day"], winning_slot["time"], winning_slot["votes"], False)
    )
    db.commit()
    flash(f"Le choix majoritaire ({winning_slot['day']} à {winning_slot['time']}) a été confirmé et figé.", "success")
    return redirect(url_for('index'))

@app.route('/export_pdf')
def export_pdf():
    final_choice_db = get_final_choice_from_db()
    if not final_choice_db:
        flash("L'export PDF n'est disponible qu'après la sélection finale d'un créneau.", "warning")
        return redirect(url_for('index'))

    db = get_db()
    all_submissions = db.execute('''
        SELECT teacher_name, day_of_week, time_slot, comment 
        FROM submissions 
        ORDER BY teacher_name, 
                 CASE day_of_week 
                    WHEN 'Lundi' THEN 1 WHEN 'Mardi' THEN 2 WHEN 'Mercredi' THEN 3 
                    WHEN 'Jeudi' THEN 4 WHEN 'Vendredi' THEN 5 ELSE 6 
                 END, 
                 time_slot
    ''').fetchall()

    submissions_by_teacher = defaultdict(list)
    for sub in all_submissions:
        submissions_by_teacher[sub['teacher_name']].append(sub)
    
    final_meeting_slot_str = f"{final_choice_db['day_of_week']} à {final_choice_db['time_slot']}"

    # Création du PDF avec ReportLab
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    
    styles = getSampleStyleSheet()
    # Définir des styles personnalisés
    styles.add(ParagraphStyle(name='Header1', parent=styles['h1'], alignment=1, fontSize=22, spaceAfter=10, textColor=colors.HexColor('#0056b3')))
    styles.add(ParagraphStyle(name='Header2', parent=styles['h2'], fontSize=15, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor('#0056b3')))
    styles.add(ParagraphStyle(name='NormalRight', parent=styles['Normal'], alignment=2)) # 2 for right alignment
    styles.add(ParagraphStyle(name='FinalSlot', parent=styles['Normal'], alignment=1, fontSize=14, spaceBefore=10, spaceAfter=10, backColor=colors.HexColor('#e7f3ff'), borderColor=colors.HexColor('#90c5ff'), borderPadding=10, leading=16))
    styles.add(ParagraphStyle(name='CommentStyle', parent=styles['Italic'], fontSize=9, textColor=colors.HexColor('#555')))
    styles.add(ParagraphStyle(name='NoChoice', parent=styles['Normal'], alignment=1, textColor=colors.HexColor('#777'), fontStyle='italic'))


    story = []

    # En-tête du PDF
    story.append(Paragraph("Récapitulatif des Disponibilités pour la Réunion", styles['Header1']))
    story.append(Paragraph(f"Document généré le {datetime.now().strftime('%d/%m/%Y')}", styles['NormalRight']))
    story.append(Spacer(1, 0.5*inch))
    
    story.append(Paragraph(f"Créneau final retenu : {final_meeting_slot_str}", styles['FinalSlot']))
    story.append(Spacer(1, 0.5*inch))

    if submissions_by_teacher:
        for teacher, submissions in submissions_by_teacher.items():
            story.append(Paragraph(f"Enseignant : {teacher}", styles['Header2']))
            
            if submissions:
                data = [["Jour", "Créneau Choisi", "Commentaire"]] # En-têtes du tableau
                for sub in submissions:
                    comment_text = sub['comment'] if sub['comment'] else "- Aucun -"
                    # Pour gérer les sauts de ligne dans les commentaires, on peut les remplacer
                    # ou utiliser des objets Paragraph dans les cellules, mais cela complexifie.
                    # Pour l'instant, on les garde en une ligne.
                    data.append([
                        Paragraph(sub['day_of_week'], styles['Normal']),
                        Paragraph(sub['time_slot'], styles['Normal']),
                        Paragraph(comment_text.replace('\n', '<br/>\n') if sub['comment'] else "- Aucun -", styles['CommentStyle'])
                    ])
                
                # Créer le tableau
                col_widths = [2.5*inch, 2*inch, 2.5*inch] # Ajustez selon besoin
                table = Table(data, colWidths=col_widths)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0f6ff')),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#004a8c')),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0,0), (-1,0), 12),
                    ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#fdfdfd')),
                    ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#cccccc')),
                    ('LEFTPADDING', (0,0), (-1,-1), 6),
                    ('RIGHTPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ]))
                story.append(table)
            else:
                story.append(Paragraph("Aucun créneau n'a été soumis par cet enseignant.", styles['NoChoice']))
            story.append(Spacer(1, 0.3*inch))
    else:
        story.append(Paragraph("Aucune soumission de disponibilité n'a été enregistrée.", styles['NoChoice']))

    # Pied de page (plus complexe à faire dynamiquement avec SimpleDocTemplate, souvent géré dans la méthode build)
    # Pour l'instant, on ajoute un simple texte à la fin du contenu.
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph(f"Planificateur de Réunion - {datetime.now().year}", styles['NormalRight']))


    doc.build(story) # Construit le PDF dans le buffer
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=recapitulatif_reunion.pdf'
    return response


if __name__ == '__main__':
    app.run(debug=True)