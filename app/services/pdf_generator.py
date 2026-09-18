import io
import datetime
from typing import List, Dict, Any, Optional
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether
)

from app.db.models import Quiz, QuizQuestion, QuizAttempt, Video


class PdfGenerator:
    """
    Generates professional, styled PDF documents for:
    1. Clean Question Paper (student test paper without answers)
    2. Comprehensive Quiz & Evaluation Report (detailed candidate scorecard with timestamps)
    """

    @staticmethod
    def generate_question_paper(quiz: Quiz, video: Video) -> io.BytesIO:
        """Generate a clean printable Question Paper PDF without answers."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )

        styles = getSampleStyleSheet()
        
        # Custom typography styles
        title_style = ParagraphStyle(
            'ExamTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=6
        )
        subtitle_style = ParagraphStyle(
            'ExamSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569")
        )
        instruction_style = ParagraphStyle(
            'Instructions',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=12
        )
        q_header_style = ParagraphStyle(
            'QuestionHeader',
            parent=styles['Heading3'],
            fontName='Helvetica-Bold',
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#0284c7"),
            spaceBefore=10,
            spaceAfter=4
        )
        q_text_style = ParagraphStyle(
            'QuestionText',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=6
        )
        option_style = ParagraphStyle(
            'OptionText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#334155")
        )
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#94a3b8"),
            alignment=1
        )

        story = []

        # 1. Header Banner
        story.append(Paragraph(f"<b>QUESTION PAPER:</b> {quiz.title or video.filename}", title_style))
        today_str = datetime.datetime.utcnow().strftime("%B %d, %Y")
        story.append(Paragraph(
            f"<b>Source Video:</b> {video.filename} &nbsp;|&nbsp; <b>Date:</b> {today_str} &nbsp;|&nbsp; "
            f"<b>Difficulty:</b> {quiz.difficulty.title()} &nbsp;|&nbsp; <b>Total Questions:</b> {quiz.total_questions}",
            subtitle_style
        ))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284c7"), spaceAfter=10))

        story.append(Paragraph(
            "<b>Instructions:</b> Read each question carefully. Select the most accurate answer based on the knowledge "
            "and demonstration presented in the video. Do NOT consult external materials.",
            instruction_style
        ))
        story.append(Spacer(1, 10))

        # 2. Questions List
        for idx, q in enumerate(quiz.questions, start=1):
            q_block = []
            type_label = (
                "Multiple Choice" if q.question_type == "mcq"
                else ("True / False" if q.question_type == "true_false" else "Short Answer")
            )
            q_block.append(Paragraph(f"Question {idx} of {quiz.total_questions} &nbsp;·&nbsp; [{type_label}] &nbsp;·&nbsp; Topic: {q.topic}", q_header_style))
            q_block.append(Paragraph(q.question, q_text_style))

            if q.question_type in ["mcq", "true_false"] and q.options:
                letters = ["A", "B", "C", "D", "E"]
                for o_idx, opt in enumerate(q.options):
                    l = letters[o_idx] if o_idx < len(letters) else "-"
                    q_block.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;<b>[{l}]</b> {opt}", option_style))
                    q_block.append(Spacer(1, 2))
            elif q.question_type == "short_answer":
                q_block.append(Spacer(1, 4))
                q_block.append(Paragraph("<i>Write your answer below:</i>", option_style))
                # Empty response box lines
                empty_box = Table([[""]], colWidths=[520], rowHeights=[45])
                empty_box.setStyle(TableStyle([
                    ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor("#cbd5e1")),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ]))
                q_block.append(empty_box)

            q_block.append(Spacer(1, 12))
            story.append(KeepTogether(q_block))

        # 3. Footer
        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=8))
        story.append(Paragraph("VideoIntel AI Assessment Platform &nbsp;·&nbsp; Automated Knowledge Verification", footer_style))

        doc.build(story)
        buffer.seek(0)
        return buffer

    @staticmethod
    def generate_answer_key_paper(quiz: Quiz, video: Video) -> io.BytesIO:
        """Generate a complete Question Paper PDF with Answer Key and Explanations."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'ExamTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=6
        )
        subtitle_style = ParagraphStyle(
            'ExamSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569")
        )
        instruction_style = ParagraphStyle(
            'Instructions',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=12
        )
        q_header_style = ParagraphStyle(
            'QuestionHeader',
            parent=styles['Heading3'],
            fontName='Helvetica-Bold',
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#0284c7"),
            spaceBefore=10,
            spaceAfter=4
        )
        q_text_style = ParagraphStyle(
            'QuestionText',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=6
        )
        option_style = ParagraphStyle(
            'OptionText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#334155")
        )
        correct_style = ParagraphStyle(
            'CorrectText',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#16a34a")
        )
        explanation_style = ParagraphStyle(
            'ExpText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#475569")
        )
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#94a3b8"),
            alignment=1
        )

        story = []

        # 1. Header Card
        story.append(Paragraph(f"<b>{quiz.title or 'Knowledge Assessment Q&A Key'}</b>", title_style))
        story.append(Paragraph(
            f"<b>Video:</b> {video.filename} &nbsp;·&nbsp; <b>Difficulty:</b> {quiz.difficulty.upper()} &nbsp;·&nbsp; <b>Type:</b> {quiz.question_type.upper()}",
            subtitle_style
        ))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=10))

        story.append(Paragraph(
            "<b>Master Answer Key &amp; Video Explanations:</b> Contains correct answers, detailed reasoning, and video timestamp citations.",
            instruction_style
        ))
        story.append(Spacer(1, 10))

        # 2. Questions List
        for idx, q in enumerate(quiz.questions, start=1):
            q_block = []
            type_label = (
                "Multiple Choice" if q.question_type == "mcq"
                else ("True / False" if q.question_type == "true_false" else "Short Answer")
            )
            time_tag = f" &nbsp;·&nbsp; [{q.relevant_timestamp_formatted}]" if q.relevant_timestamp_formatted else ""
            q_block.append(Paragraph(f"Question {idx} of {quiz.total_questions} &nbsp;·&nbsp; [{type_label}]{time_tag} &nbsp;·&nbsp; Topic: {q.topic}", q_header_style))
            q_block.append(Paragraph(q.question, q_text_style))

            if q.question_type in ["mcq", "true_false"] and q.options:
                letters = ["A", "B", "C", "D", "E"]
                for o_idx, opt in enumerate(q.options):
                    l = letters[o_idx] if o_idx < len(letters) else "-"
                    is_correct_opt = (str(opt).strip().lower() == str(q.correct_answer).strip().lower()) or (str(l).lower() == str(q.correct_answer).strip().lower())
                    if is_correct_opt:
                        q_block.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;<b>[{l}]</b> {opt} &nbsp;✔ (Correct Answer)", correct_style))
                    else:
                        q_block.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;<b>[{l}]</b> {opt}", option_style))
                    q_block.append(Spacer(1, 2))
            else:
                q_block.append(Paragraph(f"<b>Correct Answer:</b> {q.correct_answer}", correct_style))

            if q.explanation:
                q_block.append(Spacer(1, 2))
                q_block.append(Paragraph(f"<b>Explanation:</b> {q.explanation}", explanation_style))

            q_block.append(Spacer(1, 12))
            story.append(KeepTogether(q_block))

        # 3. Footer
        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=8))
        story.append(Paragraph("VideoIntel AI Assessment Platform &nbsp;·&nbsp; Automated Knowledge Verification &amp; Answer Key", footer_style))

        doc.build(story)
        buffer.seek(0)
        return buffer

    @staticmethod
    def generate_evaluation_report(attempt: QuizAttempt, quiz: Quiz, video: Video) -> io.BytesIO:
        """Generate a complete Quiz & Evaluation Report PDF with score, topic breakdown, and timestamps."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4
        )
        subtitle_style = ParagraphStyle(
            'ReportSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#475569")
        )
        section_title_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=12,
            spaceAfter=6
        )
        q_num_style = ParagraphStyle(
            'QNum',
            parent=styles['Heading3'],
            fontName='Helvetica-Bold',
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#0284c7"),
            spaceBefore=8,
            spaceAfter=3
        )
        q_text_style = ParagraphStyle(
            'QText',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=5
        )
        body_style = ParagraphStyle(
            'QBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#334155")
        )
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#94a3b8"),
            alignment=1
        )

        story = []

        # 1. Header Banner
        story.append(Paragraph("<b>QUIZ & EVALUATION REPORT</b>", title_style))
        date_str = attempt.created_at.strftime("%B %d, %Y %H:%M UTC") if attempt.created_at else datetime.datetime.utcnow().strftime("%B %d, %Y")
        story.append(Paragraph(
            f"<b>Video:</b> {video.filename} &nbsp;|&nbsp; <b>Evaluation Date:</b> {date_str}",
            subtitle_style
        ))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284c7"), spaceAfter=12))

        # 2. Scorecard Table
        score_color = colors.HexColor("#059669") if attempt.percentage >= 70 else colors.HexColor("#dc2626")
        score_data = [
            [
                Paragraph("<b>Total Score</b>", body_style),
                Paragraph("<b>Accuracy</b>", body_style),
                Paragraph("<b>Correct</b>", body_style),
                Paragraph("<b>Incorrect</b>", body_style),
                Paragraph("<b>Unanswered</b>", body_style),
            ],
            [
                Paragraph(f"<font size=14><b>{attempt.total_score:.1f} / {attempt.max_score:.0f}</b></font>", body_style),
                Paragraph(f"<font size=14 color='{score_color.hexval()}'><b>{attempt.percentage:.1f}%</b></font>", body_style),
                Paragraph(f"<font size=12 color='#059669'><b>{attempt.correct_count}</b></font>", body_style),
                Paragraph(f"<font size=12 color='#dc2626'><b>{attempt.incorrect_count}</b></font>", body_style),
                Paragraph(f"<font size=12 color='#64748b'><b>{attempt.unanswered_count}</b></font>", body_style),
            ]
        ]
        score_table = Table(score_data, colWidths=[105, 105, 105, 105, 105])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(score_table)
        story.append(Spacer(1, 14))

        # 3. Topic Diagnostics (Strong Areas vs Needs Improvement)
        eval_data = attempt.evaluation_data or {}
        strong_areas = eval_data.get("strong_areas", [])
        needs_improvement = eval_data.get("needs_improvement", [])

        story.append(Paragraph("<b>Topic Competency Diagnostics</b>", section_title_style))
        strong_text = ", ".join(strong_areas) if strong_areas else "None identified."
        needs_text = ", ".join(needs_improvement) if needs_improvement else "None identified."

        diag_data = [
            [
                Paragraph("<b>Strong Areas (Mastered &ge; 75%)</b>", body_style),
                Paragraph(f"<font color='#059669'>✓ {strong_text}</font>", body_style)
            ],
            [
                Paragraph("<b>Needs Improvement (&lt; 75%)</b>", body_style),
                Paragraph(f"<font color='#dc2626'>⚠ {needs_text}</font>", body_style)
            ]
        ]
        diag_table = Table(diag_data, colWidths=[180, 345])
        diag_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#f8fafc")),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(diag_table)
        story.append(Spacer(1, 16))

        # 4. Question-by-Question Breakdown
        story.append(Paragraph("<b>Detailed Question Review & Smart Relearn Recommendations</b>", section_title_style))

        evaluated_items = eval_data.get("evaluated_items", [])
        for idx, item in enumerate(evaluated_items, start=1):
            q_block = []
            is_corr = item.get("is_correct", False)
            is_unans = item.get("is_unanswered", False)

            if is_corr:
                status_badge = "<font color='#059669'><b>[CORRECT ✓]</b></font>"
            elif is_unans:
                status_badge = "<font color='#64748b'><b>[UNANSWERED ⚠]</b></font>"
            else:
                status_badge = "<font color='#dc2626'><b>[INCORRECT ✗]</b></font>"

            ts = item.get("relevant_timestamp_formatted", "00:00")
            q_block.append(Paragraph(
                f"Question {idx} &nbsp;·&nbsp; {status_badge} &nbsp;·&nbsp; <b>Topic:</b> {item.get('topic', 'General')}",
                q_num_style
            ))
            q_block.append(Paragraph(item.get("question", ""), q_text_style))

            ans_table_data = [
                [
                    Paragraph("<b>Your Answer:</b>", body_style),
                    Paragraph(f"<i>{item.get('user_answer', '(None)')}</i>", body_style)
                ],
                [
                    Paragraph("<b>Correct Answer:</b>", body_style),
                    Paragraph(f"<b>{item.get('correct_answer', '')}</b>", body_style)
                ],
                [
                    Paragraph("<b>Explanation:</b>", body_style),
                    Paragraph(item.get("explanation", ""), body_style)
                ],
                [
                    Paragraph("<b>Recommended Relearn:</b>", body_style),
                    Paragraph(f"<font color='#0284c7'><b>▶ Watch video section at {ts}</b></font>", body_style)
                ]
            ]
            ans_table = Table(ans_table_data, colWidths=[140, 385])
            ans_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor("#e2e8f0")),
                ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor("#f1f5f9")),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            q_block.append(ans_table)
            q_block.append(Spacer(1, 10))

            story.append(KeepTogether(q_block))

        # 5. Footer
        story.append(Spacer(1, 15))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=6))
        story.append(Paragraph("VideoIntel AI Assessment Platform &nbsp;·&nbsp; Generated with Grounded Multi-Modal Evidence", footer_style))

        doc.build(story)
        buffer.seek(0)
        return buffer


pdf_generator = PdfGenerator()

