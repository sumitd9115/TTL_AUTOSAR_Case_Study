from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

OUTPUT_PATH = "/home/claude/autosar-hld-assistant/data/Sample_AUTOSAR_HLD_BodyControlModule.pdf"

doc = SimpleDocTemplate(OUTPUT_PATH, pagesize=letter,
                         topMargin=0.75*inch, bottomMargin=0.75*inch)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='H1', fontSize=16, spaceAfter=12, spaceBefore=12, textColor=colors.HexColor("#1a3c6e")))
styles.add(ParagraphStyle(name='H2', fontSize=13, spaceAfter=8, spaceBefore=10, textColor=colors.HexColor("#2c5282")))
styles.add(ParagraphStyle(name='Body', fontSize=10, spaceAfter=8, leading=14))

story = []

def h1(text):
    story.append(Paragraph(text, styles['H1']))

def h2(text):
    story.append(Paragraph(text, styles['H2']))

def body(text):
    story.append(Paragraph(text, styles['Body']))

cell_style = ParagraphStyle(name='Cell', fontSize=8, leading=10)
header_style = ParagraphStyle(name='CellHead', fontSize=8, leading=10, textColor=colors.white)

def table(data, col_widths=None):
    # Wrap every cell in a Paragraph so long text wraps inside its column
    wrapped = [
        [Paragraph(str(cell), header_style if r == 0 else cell_style) for cell in row]
        for r, row in enumerate(data)
    ]
    t = Table(wrapped, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#2c5282")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f0f4f8")]),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

# ---------------- Cover ----------------
h1("Body Control Module (BCM)")
h1("AUTOSAR High-Level Design Document")
body("Document ID: HLD-BCM-2026-v3.2 | Classification: Internal | Project: Gen4 Platform ECU Suite")
body("Prepared by: Systems Architecture Team | Date: September 2026")
story.append(PageBreak())

# ---------------- Section 1 ----------------
h1("1. Introduction")
body("This document describes the High-Level Design (HLD) of the Body Control Module (BCM) software, "
     "developed in compliance with the AUTOSAR Classic Platform architecture. The BCM is responsible for "
     "managing body-domain functions including central locking, lighting control, window lift, and wiper control.")

h2("1.1 Scope")
body("This HLD covers the Software Component (SWC) architecture, port interfaces, signal definitions, "
     "runnable entities, and inter-component data flows for the BCM ECU. It does not cover low-level driver "
     "implementation details, which are documented separately in the MCAL Integration Guide.")

h2("1.2 Referenced Documents")
table([
    ["Doc ID", "Title", "Version"],
    ["SRS-BCM-001", "Software Requirements Specification - BCM", "2.1"],
    ["ICD-BCM-VN-002", "Interface Control Document - Vehicle Network", "1.4"],
    ["SWA-PLATFORM-010", "Gen4 Platform Software Architecture", "3.0"],
])

# ---------------- Section 2 ----------------
h1("2. Software Component Architecture")
body("The BCM software is decomposed into the following Application Software Components (SWCs), each "
     "responsible for a distinct body-domain function. Components communicate exclusively through "
     "AUTOSAR Sender-Receiver and Client-Server ports as defined in Section 3.")

h2("2.1 Component Overview")
table([
    ["Component Name", "Component ID", "Type", "Primary Responsibility"],
    ["CentralLockingMgr", "SWC-BCM-001", "Application SWC", "Manage lock/unlock requests and door state"],
    ["LightingCtrl", "SWC-BCM-002", "Application SWC", "Control exterior and interior lighting"],
    ["WindowLiftMgr", "SWC-BCM-003", "Application SWC", "Manage power window motor control and anti-pinch"],
    ["WiperCtrl", "SWC-BCM-004", "Application SWC", "Control wiper motor speed and intermittent modes"],
    ["BCM_DiagMgr", "SWC-BCM-005", "Application SWC", "Handle UDS diagnostic requests for BCM subsystems"],
    ["VehicleStateMonitor", "SWC-BCM-006", "Application SWC", "Aggregate vehicle state signals (speed, ignition)"],
])

h2("2.2 Component Dependencies")
body("CentralLockingMgr depends on VehicleStateMonitor for vehicle speed to enforce speed-based auto-lock. "
     "WindowLiftMgr depends on VehicleStateMonitor for ignition state to disable window operation when the "
     "ignition is off, unless the convenience-close feature is active. LightingCtrl depends on "
     "VehicleStateMonitor for ambient light sensor data routed through the vehicle state aggregation logic. "
     "BCM_DiagMgr has read/write access to internal diagnostic data of all other components via dedicated "
     "Client-Server interfaces.")

# ---------------- Section 3 ----------------
story.append(PageBreak())
h1("3. Port and Interface Definitions")

h2("3.1 CentralLockingMgr Ports")
table([
    ["Port Name", "Direction", "Interface Type", "Data Element / Operation"],
    ["PPort_LockRequest", "Provided", "Sender-Receiver", "LockRequestStatus (enum: LOCKED, UNLOCKED, PENDING)"],
    ["RPort_DoorState", "Required", "Sender-Receiver", "DoorState (bitfield, 4 doors)"],
    ["RPort_VehicleSpeed", "Required", "Sender-Receiver", "VehicleSpeed_kph (uint16)"],
    ["PPort_DiagAccess", "Provided", "Client-Server", "ReadLockStatus(), WriteLockOverride()"],
], col_widths=[1.6*inch, 0.9*inch, 1.3*inch, 2.5*inch])

h2("3.2 WindowLiftMgr Ports")
table([
    ["Port Name", "Direction", "Interface Type", "Data Element / Operation"],
    ["PPort_WindowPos", "Provided", "Sender-Receiver", "WindowPosition_pct (uint8, per door)"],
    ["RPort_IgnitionState", "Required", "Sender-Receiver", "IgnitionState (enum: OFF, ACC, RUN, START)"],
    ["RPort_PinchDetect", "Required", "Sender-Receiver", "PinchForce_N (uint16, from sensor SWC)"],
    ["PPort_DiagAccess", "Provided", "Client-Server", "ReadWindowPosition(), CalibrateWindow()"],
], col_widths=[1.6*inch, 0.9*inch, 1.3*inch, 2.5*inch])

h2("3.3 LightingCtrl Ports")
table([
    ["Port Name", "Direction", "Interface Type", "Data Element / Operation"],
    ["PPort_LightState", "Provided", "Sender-Receiver", "LightState (bitfield: head/tail/fog/hazard)"],
    ["RPort_AmbientLight", "Required", "Sender-Receiver", "AmbientLightLevel_lux (uint16)"],
    ["RPort_IgnitionState", "Required", "Sender-Receiver", "IgnitionState (enum)"],
], col_widths=[1.6*inch, 0.9*inch, 1.3*inch, 2.5*inch])

# ---------------- Section 4 ----------------
story.append(PageBreak())
h1("4. Runnable Entities and Scheduling")
body("Each SWC exposes one or more Runnable Entities mapped to OS tasks via the RTE. The table below "
     "summarizes runnable periodicity and trigger conditions.")

table([
    ["Runnable Name", "Owning SWC", "Trigger", "Period"],
    ["Rte_CentralLock_10ms", "CentralLockingMgr", "Timed", "10 ms"],
    ["Rte_CentralLock_OnLockEvent", "CentralLockingMgr", "Data Received Event", "Event-driven"],
    ["Rte_WindowLift_20ms", "WindowLiftMgr", "Timed", "20 ms"],
    ["Rte_WindowLift_OnPinch", "WindowLiftMgr", "Data Received Event", "Event-driven"],
    ["Rte_Lighting_50ms", "LightingCtrl", "Timed", "50 ms"],
    ["Rte_Wiper_20ms", "WiperCtrl", "Timed", "20 ms"],
    ["Rte_Diag_OnRequest", "BCM_DiagMgr", "Client-Server Invocation", "Event-driven"],
    ["Rte_VehicleState_10ms", "VehicleStateMonitor", "Timed", "10 ms"],
])

# ---------------- Section 5 ----------------
h1("5. Functional Flow: Auto-Lock on Speed Threshold")
body("The following describes the end-to-end functional flow for the vehicle speed-based auto-lock feature, "
     "a safety-relevant convenience function.")
body("1. VehicleStateMonitor reads raw vehicle speed from the CAN gateway signal VSS_Speed and publishes "
     "VehicleSpeed_kph via RPort_VehicleSpeed at 10 ms intervals.")
body("2. CentralLockingMgr's Rte_CentralLock_10ms runnable evaluates whether VehicleSpeed_kph exceeds the "
     "configured threshold (default: 15 kph, calibratable via BCM_DiagMgr).")
body("3. If the threshold is exceeded and all doors report DoorState = CLOSED, CentralLockingMgr transitions "
     "internal state to PENDING and issues a lock command via PPort_LockRequest.")
body("4. The lock actuator driver (outside SWC scope, handled by Complex Device Driver) executes the "
     "physical lock and reports completion, at which point LockRequestStatus transitions to LOCKED.")
body("5. BCM_DiagMgr logs the auto-lock event with timestamp for UDS diagnostic readout (DID 0xF190 series).")

# ---------------- Section 6 ----------------
story.append(PageBreak())
h1("6. Known Open Issues and Design Notes")
table([
    ["ID", "Description", "Status"],
    ["ISS-014", "WindowLiftMgr does not currently subscribe to PinchForce_N from all four door sensor SWCs; "
     "only front doors are wired in current revision.", "Open"],
    ["ISS-021", "LightingCtrl ambient light threshold for auto-headlamp activation is hardcoded; should be "
     "migrated to a calibratable parameter in next revision.", "Open"],
    ["ISS-027", "No explicit timeout defined for PENDING lock state if actuator fails to confirm; potential "
     "gap for stuck-state diagnostic monitoring.", "Open"],
], col_widths=[0.7*inch, 4.8*inch, 0.8*inch])

h1("7. Revision History")
table([
    ["Version", "Date", "Author", "Change Summary"],
    ["1.0", "2025-03-10", "System Architecture Team", "Initial release"],
    ["2.0", "2025-08-22", "System Architecture Team", "Added WiperCtrl and BCM_DiagMgr components"],
    ["3.0", "2026-02-15", "System Architecture Team", "Restructured ports for VehicleStateMonitor aggregation"],
    ["3.2", "2026-09-01", "System Architecture Team", "Added known issues section; updated auto-lock flow"],
])

doc.build(story)
print(f"Generated: {OUTPUT_PATH}")
