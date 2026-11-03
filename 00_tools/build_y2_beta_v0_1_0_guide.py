#!/usr/bin/env python3
"""Build the illustrated Y2 Rockbox Beta v0.1.0 user guide."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import fitz
from PIL import Image as PILImage
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


RELEASE = "Y2 Rockbox Beta v0.1.0"
FIRMWARE_NAME = "Y2-Rockbox-Beta-v0.1.0-V88-InnioasisUpdater.zip"
FIRMWARE_SHA256 = (
    "40636D86943F6F0A1461B6D8C9285A1A50252253447B3DC7D11743533A88E4DE"
)
FLASHER_SHA256 = (
    "7FA6FF6677B74E7A1D4068FA309DBE5128AB37764C46DE930215471D7418C46F"
)

NAVY = colors.HexColor("#172033")
BLUE = colors.HexColor("#316BFF")
PALE_BLUE = colors.HexColor("#EEF3FF")
GREEN = colors.HexColor("#14804A")
PALE_GREEN = colors.HexColor("#EAF8F0")
ORANGE = colors.HexColor("#B54708")
PALE_ORANGE = colors.HexColor("#FFF3E8")
RED = colors.HexColor("#B42318")
PALE_RED = colors.HexColor("#FDECEC")
GREY = colors.HexColor("#667085")
LIGHT_GREY = colors.HexColor("#EAECF0")
INK = colors.HexColor("#1D2939")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def safe_font_registration() -> tuple[str, str]:
    regular = Path(r"C:\Windows\Fonts\segoeui.ttf")
    bold = Path(r"C:\Windows\Fonts\segoeuib.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("GuideSans", str(regular)))
        pdfmetrics.registerFont(TTFont("GuideSans-Bold", str(bold)))
        return "GuideSans", "GuideSans-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = safe_font_registration()


def crop_page(
    document: fitz.Document,
    page_index: int,
    fractions: tuple[float, float, float, float],
    output: Path,
) -> None:
    page = document[page_index]
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    temporary = output.with_suffix(".full.png")
    pixmap.save(temporary)
    with PILImage.open(temporary) as source:
        width, height = source.size
        left, top, right, bottom = fractions
        cropped = source.crop(
            (
                int(width * left),
                int(height * top),
                int(width * right),
                int(height * bottom),
            )
        )
        cropped.save(output, optimize=True)
    temporary.unlink()


def prepare_visuals(vendor_guide: Path, work: Path) -> dict[str, Path]:
    work.mkdir(parents=True, exist_ok=True)
    document = fitz.open(vendor_guide)
    outputs = {
        "driver": work / "driver-install.png",
        "choose": work / "choose-package.png",
        "selected": work / "package-selected.png",
        "progress": work / "flash-progress.png",
        "complete": work / "flash-complete.png",
    }
    crop_page(document, 0, (0.14, 0.40, 0.86, 0.80), outputs["driver"])
    crop_page(document, 2, (0.14, 0.28, 0.86, 0.56), outputs["choose"])
    crop_page(document, 3, (0.14, 0.07, 0.86, 0.43), outputs["selected"])
    crop_page(document, 3, (0.14, 0.43, 0.86, 0.79), outputs["progress"])
    crop_page(document, 4, (0.14, 0.07, 0.86, 0.43), outputs["complete"])
    document.close()
    return outputs


def scaled_image(path: Path, width: float, max_height: float | None = None) -> Image:
    with PILImage.open(path) as source:
        image_width, image_height = source.size
    height = width * image_height / image_width
    if max_height is not None and height > max_height:
        height = max_height
        width = height * image_width / image_height
    return Image(str(path), width=width, height=height)


def callout(
    title: str,
    text: str,
    background: colors.Color,
    foreground: colors.Color,
    styles: dict[str, ParagraphStyle],
) -> Table:
    content = Paragraph(
        f"<b>{title}</b><br/>{text}",
        styles["callout"],
    )
    table = Table([[content]], colWidths=[174 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.8, foreground),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TEXTCOLOR", (0, 0), (-1, -1), foreground),
            ]
        )
    )
    return table


def step_table(
    rows: list[tuple[str, str]],
    styles: dict[str, ParagraphStyle],
) -> Table:
    data = []
    for number, text in rows:
        badge = Paragraph(f"<b>{number}</b>", styles["step_badge"])
        body = Paragraph(text, styles["body"])
        data.append([badge, body])
    table = Table(data, colWidths=[13 * mm, 158 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
                ("BOX", (0, 0), (0, -1), 0.6, BLUE),
                ("LINEBELOW", (1, 0), (1, -2), 0.4, LIGHT_GREY),
                ("LEFTPADDING", (0, 0), (0, -1), 4),
                ("RIGHTPADDING", (0, 0), (0, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (1, 0), (1, -1), 8),
            ]
        )
    )
    return table


def route_drawing() -> Drawing:
    drawing = Drawing(490, 178)
    drawing.add(Rect(7, 126, 105, 38, 8, 8, fillColor=NAVY, strokeColor=NAVY))
    drawing.add(String(59, 148, "Y2 powered off", fontName=FONT_BOLD,
                       fontSize=10, fillColor=colors.white, textAnchor="middle"))
    drawing.add(String(59, 135, "Start here", fontName=FONT,
                       fontSize=8, fillColor=colors.white, textAnchor="middle"))

    routes = [
        ("No volume", "Rockbox", 8, GREEN, PALE_GREEN),
        ("Volume Up", "Stock Y2", 132, BLUE, PALE_BLUE),
        ("Volume Down", "Boot Settings", 256, ORANGE, PALE_ORANGE),
        ("Both volume", "Unavailable in beta", 380, RED, PALE_RED),
    ]
    for label, result, x, edge, fill in routes:
        drawing.add(Line(60, 126, x + 48, 98, strokeColor=GREY, strokeWidth=1))
        drawing.add(Rect(x, 40, 105, 54, 7, 7, fillColor=fill, strokeColor=edge))
        drawing.add(String(x + 52, 75, label, fontName=FONT_BOLD,
                           fontSize=9, fillColor=edge, textAnchor="middle"))
        drawing.add(String(x + 52, 58, result, fontName=FONT,
                           fontSize=8, fillColor=INK, textAnchor="middle"))
        drawing.add(String(x + 52, 21, "Hold, then press Power",
                           fontName=FONT, fontSize=7.5,
                           fillColor=GREY, textAnchor="middle"))
    return drawing


def usb_drawing() -> Drawing:
    drawing = Drawing(490, 100)
    boxes = [
        ("Connect", 0),
        ("Enable USB", 100),
        ("Copy files", 200),
        ("Safe eject", 300),
        ("Disable + unplug", 400),
    ]
    for index, (label, x) in enumerate(boxes):
        drawing.add(Rect(x + 2, 34, 84, 36, 7, 7,
                         fillColor=PALE_BLUE, strokeColor=BLUE))
        drawing.add(String(x + 44, 54, label, fontName=FONT_BOLD,
                           fontSize=8.5, fillColor=NAVY, textAnchor="middle"))
        if index < len(boxes) - 1:
            drawing.add(Line(x + 87, 52, x + 99, 52,
                             strokeColor=GREY, strokeWidth=1.2))
            drawing.add(Line(x + 95, 56, x + 99, 52,
                             strokeColor=GREY, strokeWidth=1.2))
            drawing.add(Line(x + 95, 48, x + 99, 52,
                             strokeColor=GREY, strokeWidth=1.2))
    return drawing


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=28,
            leading=32,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            fontName=FONT,
            fontSize=13,
            leading=18,
            textColor=GREY,
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            fontName=FONT_BOLD,
            fontSize=22,
            leading=26,
            textColor=NAVY,
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            fontName=FONT_BOLD,
            fontSize=13,
            leading=16,
            textColor=NAVY,
            spaceBefore=7,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=FONT,
            fontSize=9.4,
            leading=13.2,
            textColor=INK,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "Small",
            fontName=FONT,
            fontSize=7.6,
            leading=10,
            textColor=GREY,
            spaceAfter=4,
        ),
        "callout": ParagraphStyle(
            "Callout",
            fontName=FONT,
            fontSize=9,
            leading=12.5,
            textColor=INK,
        ),
        "step_badge": ParagraphStyle(
            "StepBadge",
            fontName=FONT_BOLD,
            fontSize=10,
            leading=12,
            textColor=BLUE,
            alignment=TA_CENTER,
        ),
        "mono": ParagraphStyle(
            "Mono",
            fontName="Courier",
            fontSize=7.3,
            leading=10,
            textColor=INK,
            backColor=colors.HexColor("#F8FAFC"),
            borderColor=LIGHT_GREY,
            borderWidth=0.5,
            borderPadding=6,
            spaceAfter=7,
        ),
        "caption": ParagraphStyle(
            "Caption",
            fontName=FONT,
            fontSize=7,
            leading=9,
            textColor=GREY,
            alignment=TA_CENTER,
            spaceBefore=3,
            spaceAfter=7,
        ),
        "cover_badge": ParagraphStyle(
            "CoverBadge",
            fontName=FONT_BOLD,
            fontSize=11,
            leading=14,
            textColor=GREEN,
            alignment=TA_CENTER,
        ),
    }


def build_pdf(
    output: Path,
    firmware: Path,
    flasher: Path,
    vendor_guide: Path,
    menu_image: Path,
    wps_image: Path,
    work: Path,
) -> None:
    firmware_hash = sha256(firmware)
    flasher_hash = sha256(flasher)
    if firmware_hash != FIRMWARE_SHA256:
        raise SystemExit(f"Unexpected V88 firmware SHA-256: {firmware_hash}")
    if flasher_hash != FLASHER_SHA256:
        raise SystemExit(f"Unexpected flasher SHA-256: {flasher_hash}")

    visuals = prepare_visuals(vendor_guide, work)
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = build_styles()

    def header_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(LIGHT_GREY)
        canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 9 * mm, RELEASE)
        canvas.drawRightString(192 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
        title=f"{RELEASE} - Flashing and User Guide",
        author="Y2 Rockbox contributors",
        subject="Installation, operation, USB storage, themes and recovery",
    )
    story = []

    # Cover
    story.append(Spacer(1, 15 * mm))
    story.append(Paragraph("Y2 ROCKBOX", styles["title"]))
    story.append(Paragraph("Beta v0.1.0", styles["title"]))
    badge = Table(
        [[Paragraph("PHYSICALLY TESTED V88 BASE", styles["cover_badge"])]],
        colWidths=[75 * mm],
    )
    badge.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.8, GREEN),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(badge)
    story.append(Spacer(1, 9 * mm))
    story.append(
        Paragraph(
            "Flashing, first boot, everyday controls, USB storage, themes and recovery",
            styles["subtitle"],
        )
    )
    story.append(HRFlowable(width="100%", color=BLUE, thickness=2))
    story.append(Spacer(1, 8 * mm))
    facts = [
        ["Device", "Innioasis Y2 only"],
        ["Stock base", "Y2 firmware 3.1.7 / Android 4.4.2"],
        ["Installer", "InnioasisUpdater 1.1.2 on Windows"],
        ["Internal build", "V88 route readback repair"],
        ["Release date", "29 July 2026"],
    ]
    facts_table = Table(facts, colWidths=[39 * mm, 125 * mm])
    facts_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), FONT_BOLD),
                ("FONTNAME", (1, 0), (1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
                ("TEXTCOLOR", (1, 0), (1, -1), INK),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, LIGHT_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(facts_table)
    story.append(Spacer(1, 10 * mm))
    story.append(
        callout(
            "Beta warning",
            "Flashing erases the complete player. Back up internal storage, microSD "
            "content and the entire .rockbox folder before continuing. Bluetooth "
            "and the both-volume fastboot shortcut are not validated.",
            PALE_RED,
            RED,
            styles,
        )
    )
    story.append(PageBreak())

    # Before starting
    story.append(Paragraph("1. Before you start", styles["h1"]))
    story.append(
        Paragraph(
            "Use this release only on the English Innioasis Y2 based on firmware "
            "3.1.7. Do not use it on a Y1, another MediaTek player or a different "
            "Y2 firmware layout.",
            styles["body"],
        )
    )
    story.append(Paragraph("Required release files", styles["h2"]))
    asset_rows = [
        ["Firmware", FIRMWARE_NAME],
        ["Flasher", "InnioasisUpdater_Setup_1.1.2.exe"],
        ["Guide", "Y2-Rockbox-Beta-v0.1.0-Guide.pdf"],
        ["Checksums", "SHA256SUMS.txt"],
        ["Source", "Y2-Rockbox-Beta-v0.1.0-Source.zip"],
    ]
    assets = Table(asset_rows, colWidths=[31 * mm, 139 * mm])
    assets.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), FONT_BOLD),
                ("FONTNAME", (1, 0), (1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
                ("GRID", (0, 0), (-1, -1), 0.4, LIGHT_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(assets)
    story.append(Paragraph("Pre-flight checklist", styles["h2"]))
    story.append(
        step_table(
            [
                ("1", "Charge the Y2 and use a reliable USB data cable directly "
                 "connected to the Windows PC."),
                ("2", "Copy all music and files from internal storage and microSD. "
                 "Also copy the complete hidden <b>.rockbox</b> directory."),
                ("3", "Keep the official stock Y2 recovery package available. The "
                 "Rockbox release does not replace your stock recovery copy."),
                ("4", "Close other phone, sync and MediaTek utilities that could "
                 "claim the USB device."),
                ("5", "Verify the firmware and flasher against SHA256SUMS.txt."),
            ],
            styles,
        )
    )
    story.append(Paragraph("PowerShell checksum example", styles["h2"]))
    story.append(
        Paragraph(
            "Get-FileHash '.\\Y2-Rockbox-Beta-v0.1.0-V88-InnioasisUpdater.zip' "
            "-Algorithm SHA256",
            styles["mono"],
        )
    )
    story.append(
        callout(
            "Expected firmware SHA-256",
            FIRMWARE_SHA256,
            PALE_GREEN,
            GREEN,
            styles,
        )
    )
    story.append(PageBreak())

    # Install flasher
    story.append(Paragraph("2. Install InnioasisUpdater", styles["h1"]))
    story.append(
        Paragraph(
            "This release uses the Windows InnioasisUpdater 1.1.2 setup supplied "
            "for the Y2. The setup is not digitally signed, so Windows may show a "
            "publisher warning. Confirm the filename and checksum before allowing it.",
            styles["body"],
        )
    )
    story.append(
        step_table(
            [
                ("1", "Run <b>InnioasisUpdater_Setup_1.1.2.exe</b>."),
                ("2", "Approve the Windows administrator prompt only after checking "
                 "the exact filename and SHA-256."),
                ("3", "Complete the updater installation and its bundled MediaTek "
                 "USB-driver installer."),
                ("4", "Restart Windows if the installer requests it."),
                ("5", "Open Innioasis Updater before connecting the powered-off Y2."),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(scaled_image(visuals["driver"], 145 * mm, 85 * mm))
    story.append(
        Paragraph(
            "The bundled driver stage may contain Chinese text. Use the highlighted "
            "Install/Next/Finish controls shown by the Innioasis tutorial.",
            styles["caption"],
        )
    )
    story.append(
        callout(
            "Flasher checksum",
            FLASHER_SHA256,
            PALE_ORANGE,
            ORANGE,
            styles,
        )
    )
    story.append(PageBreak())

    # Select package
    story.append(Paragraph("3. Select the beta firmware", styles["h1"]))
    story.append(
        step_table(
            [
                ("1", "Leave the Y2 disconnected and fully powered off."),
                ("2", "In Innioasis Updater, click <b>Choose Package</b>."),
                ("3", f"Select <b>{FIRMWARE_NAME}</b>. Select the ZIP itself; do "
                 "not extract it."),
                ("4", "Confirm the updater shows the chosen package and reports it "
                 "ready to flash."),
                ("5", "Re-read the selected filename before pressing Start Flash."),
            ],
            styles,
        )
    )
    images = Table(
        [
            [
                scaled_image(visuals["choose"], 81 * mm, 66 * mm),
                scaled_image(visuals["selected"], 81 * mm, 66 * mm),
            ]
        ],
        colWidths=[86 * mm, 86 * mm],
    )
    images.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(Spacer(1, 5 * mm))
    story.append(images)
    story.append(
        Paragraph(
            "Left: Choose Package. Right: the selected-package state. Screenshots "
            "are from the Innioasis Y2 flashing tutorial; filenames differ.",
            styles["caption"],
        )
    )
    story.append(
        callout(
            "Do not substitute files",
            "Never choose a Y1 package, a three-partition development ZIP, an "
            "individual image or an unpacked folder.",
            PALE_RED,
            RED,
            styles,
        )
    )
    story.append(PageBreak())

    # Flash
    story.append(Paragraph("4. Flash the Y2", styles["h1"]))
    story.append(
        step_table(
            [
                ("1", "Click <b>Start Flash</b>."),
                ("2", "Make sure the Y2 is completely powered off. A gentle press "
                 "of the bottom reset/pinhole can force shutdown."),
                ("3", "Connect the powered-off Y2 with the USB data cable. If it is "
                 "not detected, leave the cable connected and gently press the "
                 "reset/pinhole once."),
                ("4", "The updater detects, erases and writes the complete firmware. "
                 "Do not disconnect the cable, close the program or power the PC off."),
                ("5", "Wait for 100% and <b>Flash Complete</b>. Only then disconnect "
                 "the cable and start the Y2."),
            ],
            styles,
        )
    )
    flash_images = Table(
        [
            [
                scaled_image(visuals["progress"], 81 * mm, 68 * mm),
                scaled_image(visuals["complete"], 81 * mm, 68 * mm),
            ]
        ],
        colWidths=[86 * mm, 86 * mm],
    )
    flash_images.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(Spacer(1, 4 * mm))
    story.append(flash_images)
    story.append(
        Paragraph(
            "The erase/write progress and completed states. Do not treat a partial "
            "percentage or an error dialog as success.",
            styles["caption"],
        )
    )
    story.append(
        callout(
            "Stop on any error",
            "Do not change flashing modes, mix firmware files or repeatedly retry. "
            "Record the exact error, preserve the updater log and use the official "
            "Y2 stock-recovery package.",
            PALE_RED,
            RED,
            styles,
        )
    )
    story.append(PageBreak())

    # First boot
    story.append(Paragraph("5. First boot and boot choices", styles["h1"]))
    story.append(
        Paragraph(
            "The first boot can take longer while Android and Rockbox prepare their "
            "resources. Let it finish before forcing a restart or connecting USB.",
            styles["body"],
        )
    )
    story.append(route_drawing())
    route_rows = [
        ["Power-on input", "Default result"],
        ["No volume button", "Rockbox"],
        ["Volume Up", "Stock Y2 interface"],
        ["Volume Down", "Boot Settings"],
        ["Volume Up + Volume Down", "Configured for fastboot, but unavailable in beta"],
    ]
    route_table = Table(route_rows, colWidths=[73 * mm, 99 * mm])
    route_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(route_table)
    story.append(Paragraph("Changing the normal-boot player", styles["h2"]))
    story.append(
        step_table(
            [
                ("1", "Power off, hold Volume Down, then press Power."),
                ("2", "Choose Rockbox or Y2 Stock under Normal boot."),
                ("3", "Choose Save & Restart."),
                ("4", "Require 'Saving...' and then 'Saved - restarting...'."),
                ("5", "After restart, Volume Up always opens the other player."),
            ],
            styles,
        )
    )
    story.append(PageBreak())

    # Controls
    story.append(Paragraph("6. Using Rockbox", styles["h1"]))
    control_rows = [
        ["Control", "Typical action"],
        ["Wheel", "Move through menus and lists"],
        ["Centre", "Select / confirm / wake display"],
        ["Previous / Next", "Left and right; previous and next track"],
        ["Back", "Return to the previous screen"],
        ["Play/Pause", "Toggle playback"],
        ["Volume Up / Down", "Change volume"],
        ["Power (hold about 3 seconds)", "Normal power action"],
    ]
    controls = Table(control_rows, colWidths=[66 * mm, 106 * mm])
    controls.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.4),
                ("GRID", (0, 0), (-1, -1), 0.45, LIGHT_GREY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(controls)
    story.append(Spacer(1, 6 * mm))
    ui = Table(
        [
            [
                scaled_image(menu_image, 79 * mm, 60 * mm),
                scaled_image(wps_image, 79 * mm, 60 * mm),
            ]
        ],
        colWidths=[86 * mm, 86 * mm],
    )
    ui.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(ui)
    story.append(
        Paragraph(
            "Rockbox menu and now-playing examples at the Y2's 480x360 resolution.",
            styles["caption"],
        )
    )
    story.append(
        Paragraph(
            "Music can be browsed from Files or indexed with Database. Internal "
            "storage and microSD playback passed the beta test. Bluetooth playback "
            "has not been tested.",
            styles["body"],
        )
    )
    story.append(PageBreak())

    # USB
    story.append(Paragraph("7. USB storage", styles["h1"]))
    story.append(usb_drawing())
    story.append(
        step_table(
            [
                ("1", "Boot Rockbox, connect the USB cable and enable USB storage "
                 "when prompted."),
                ("2", "Rockbox may close while Android exports its storage. This is "
                 "expected."),
                ("3", "Copy music, playlists or theme files. Do not alter the "
                 ".rockbox tree unless you are intentionally installing a theme."),
                ("4", "Use Windows Safely Remove/Eject for every exposed Y2 volume."),
                ("5", "Disable USB storage on the Y2 if prompted, then unplug."),
                ("6", "Wait for storage to remount and for Rockbox to return before "
                 "restarting or reconnecting."),
            ],
            styles,
        )
    )
    story.append(
        callout(
            "USB result in this beta",
            "File transfer and automatic Rockbox return passed. SNAZZ3's black "
            "30-pixel margins are part of that theme and are not USB scaling.",
            PALE_GREEN,
            GREEN,
            styles,
        )
    )
    story.append(Paragraph("If storage does not return", styles["h2"]))
    story.append(
        Paragraph(
            "Leave the cable disconnected for a moment. If files or themes are still "
            "missing, perform a normal power off and cold boot. Do not reconnect and "
            "write to a volume that Windows has not safely ejected.",
            styles["body"],
        )
    )
    story.append(PageBreak())

    # Themes
    story.append(Paragraph("8. Installing themes", styles["h1"]))
    story.append(
        Paragraph(
            "Use themes designed for a 480x360 Rockbox screen or themes specifically "
            "ported for the Innioasis Y1/Y2 360p display. A theme is usually a group "
            "of files, not just one .cfg file.",
            styles["body"],
        )
    )
    tree = (
        ".rockbox/<br/>"
        "&nbsp;&nbsp;themes/&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;ThemeName.cfg<br/>"
        "&nbsp;&nbsp;wps/&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "ThemeName.wps, ThemeName.sbs, images/<br/>"
        "&nbsp;&nbsp;fonts/&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;required .fnt files<br/>"
        "&nbsp;&nbsp;icons/&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;optional icon sets<br/>"
        "&nbsp;&nbsp;backdrops/&nbsp;&nbsp;&nbsp;optional background images"
    )
    story.append(Paragraph(tree, styles["mono"]))
    story.append(
        step_table(
            [
                ("1", "Download and extract the theme on the computer."),
                ("2", "Connect the Y2, enable USB storage and show hidden files."),
                ("3", "Back up the existing <b>.rockbox</b> directory."),
                ("4", "Merge the theme's complete <b>.rockbox</b> directory into the "
                 "existing directory at the root of internal storage."),
                ("5", "Do not replace or delete the complete existing .rockbox tree."),
                ("6", "Safely eject, disable USB storage, unplug and wait for Rockbox."),
                ("7", "Open Settings > Theme Settings > Browse Themes, select the "
                 "theme, then cold boot once to confirm it persists."),
            ],
            styles,
        )
    )
    story.append(
        callout(
            "About SNAZZ3",
            "SNAZZ3 deliberately uses a 420-pixel menu viewport with 30-pixel side "
            "margins. Its black background can make the whole interface look smaller. "
            "MacClassic uses almost the full 480x360 screen. Both are correct.",
            PALE_ORANGE,
            ORANGE,
            styles,
        )
    )
    story.append(PageBreak())

    # Recovery / limits
    story.append(Paragraph("9. Recovery and beta limitations", styles["h1"]))
    story.append(Paragraph("Known limitations", styles["h2"]))
    limitations = [
        ["Bluetooth", "Untested"],
        ["Both-volume fastboot chord", "Did not open fastboot; do not rely on it"],
        ["Date and time persistence", "Observed not saving; stock relationship unknown"],
        ["Flashing", "Full-device erase through format-download"],
        ["SNAZZ3 inset", "Intentional theme layout, not a display fault"],
    ]
    limits = Table(limitations, colWidths=[67 * mm, 105 * mm])
    limits.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), FONT_BOLD),
                ("FONTNAME", (1, 0), (1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8.3),
                ("GRID", (0, 0), (-1, -1), 0.45, LIGHT_GREY),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1),
                 [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(limits)
    story.append(Paragraph("Recovery", styles["h2"]))
    story.append(
        Paragraph(
            "Keep the official Y2 stock firmware and Innioasis instructions available. "
            "For a frozen device, a gentle press of the bottom reset/pinhole forces "
            "shutdown; it is not a factory reset. For firmware recovery, open the "
            "updater, select the official complete Y2 stock package, start flashing, "
            "connect the powered-off player and use the pinhole detection sequence if "
            "needed.",
            styles["body"],
        )
    )
    story.append(
        callout(
            "Do not improvise recovery",
            "Never use a Y1 preloader, scatter or firmware package. Stop on a flash "
            "error and preserve the exact updater message and log.",
            PALE_RED,
            RED,
            styles,
        )
    )
    story.append(Paragraph("Official support", styles["h2"]))
    story.append(
        Paragraph(
            "Reset and recovery information:<br/>"
            "https://www.innioasis.com/a/docs/y2/reset-your-device",
            styles["mono"],
        )
    )
    story.append(Paragraph("Licensing and source", styles["h2"]))
    story.append(
        Paragraph(
            "The release folder includes LICENSE.txt, NOTICE.txt and the complete "
            "corresponding source archive for the modified Rockbox binary. The "
            "Innioasis updater and firmware components remain third-party materials.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            "End of guide - verify SHA256SUMS.txt before flashing.",
            ParagraphStyle(
                "End",
                parent=styles["body"],
                fontName=FONT_BOLD,
                textColor=NAVY,
                alignment=TA_CENTER,
                spaceBefore=10,
            ),
        )
    )

    document.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--firmware",
        type=Path,
        default=Path(
            "build-intermediates/y2-v88-route-readback-repair-innioasis-full.zip"
        ),
    )
    parser.add_argument(
        "--flasher",
        type=Path,
        default=Path("Y2 - Stock/InnioasisUpdater_Setup_1.1.2.exe"),
    )
    parser.add_argument(
        "--vendor-guide",
        type=Path,
        default=Path("Flashing-tutorial-y2_v3.1.7-20260601.pdf"),
    )
    parser.add_argument(
        "--menu-image",
        type=Path,
        default=Path("11_rockbox_android/rockbox-y1/img/360p_menu.png"),
    )
    parser.add_argument(
        "--wps-image",
        type=Path,
        default=Path("11_rockbox_android/rockbox-y1/img/360p_wps.png"),
    )
    parser.add_argument(
        "--work",
        type=Path,
        default=Path("tmp/pdfs/y2-beta-v0.1.0"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/Y2-Rockbox-Beta-v0.1.0-Guide.pdf"),
    )
    args = parser.parse_args()

    required = [
        args.firmware,
        args.flasher,
        args.vendor_guide,
        args.menu_image,
        args.wps_image,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing required input(s): " + ", ".join(missing))

    build_pdf(
        args.output,
        args.firmware,
        args.flasher,
        args.vendor_guide,
        args.menu_image,
        args.wps_image,
        args.work,
    )
    print(args.output)


if __name__ == "__main__":
    main()
