"""Importa clientes históricos del tenant Sambil (plantilla one-off)."""

from django.db import migrations

SAMBIL_WORKSPACE_SLUG = "sambil"
HISTORICAL_NOTES = "Cliente histórico migrado"

_SAMBIL_HISTORICAL_CLIENTS = [
    {
        "company_name": "MALL ADVERTISING PUBLICIDAD, C.A.",
        "email": "proyectos.mallp@gmail.com",
        "rif": "J-30517802-0",
        "contact_name": "MARIA GABRIELA SCARPA",
        "representative_name": "MARIA GABRIELA SCARPA",
        "representative_id_number": "V-13.308.781",
        "phone": "58 412 3213501",
        "address": (
            "AV TRES ENTRE 6TA Y 7MA TRANSVERSAL QTA LA CUADRA CREATIVA NRO LOCAL 20, "
            "URB CHACAO, CARACAS (CHACAO) MIRANDA"
        ),
        "city": "CARACAS",
    },
    {
        "company_name": "FARMATODO, C.A",
        "email": "gabriella.dachille@farmatodo.com",
        "rif": "J-00020200-1",
        "contact_name": "GABRIELLA D'ACHILLE",
        "representative_name": "SORAYA HOBAICA",
        "representative_id_number": "V-2.766.178",
        "phone": "58 424 1503056",
        "address": (
            "AV LOS GUAYABITOS, CC EXPRESO BARUTA, NIVEL 5, OF UNICA, URB LA TRINIDAD, "
            "(SECTOR PIEDRA AZUL) CARACAS, MIRANDA."
        ),
        "city": "CARACAS",
    },
    {
        "company_name": "GRUPO CASHEA VE, C.A",
        "email": "victoriaferro@cashea.app",
        "rif": "J-50193407-0",
        "contact_name": "VICTORIA FERRO",
        "representative_name": "EZEQUIEL ZAMORA ARCAYA",
        "representative_id_number": "V-16.030.355",
        "phone": "58 424 2182856",
        "address": (
            "AV DON EUGENIO MENDOZA EDIF CENTRO LETONIA TORRE ING BANK PISO 9 Y 19 "
            "OF 94 95, 96 Y 181 URB LA CASTELLANA CARACAS"
        ),
        "city": "CARACAS",
    },
    {
        "company_name": "INVERSIONES CANAIMA 48, C.A.",
        "email": "Antonio@aktbrands.com",
        "rif": "J-41094198-7",
        "contact_name": "ANTONIO KASABDJI",
        "representative_name": "ANTONIO KASABDJI",
        "representative_id_number": "V-15.508.087",
        "phone": "58 414 2114602",
        "address": (
            "CALLE LA FACULTAD CON CALLE RAZETTI QTA LONTANANZA NRO S/N "
            "URB LOS CHAGUARAMOS CARACAS DISTRITO CAPITAL"
        ),
        "city": "CARACAS",
    },
    {
        "company_name": "OPERADORA 50 C.A",
        "email": "MANUELBALZA@GMAIL.COM",
        "rif": "J-50548399-4",
        "contact_name": "MANUEL BALZA",
        "representative_name": "PEDRO JOSÉ CALDERON RIVAS",
        "representative_id_number": "V-12.350.727",
        "phone": "58 4144042854",
        "address": (
            "AV 91-B  CC SAMBIL VALENCIA NIVEL DIVERSION LOCAL D-03 "
            "URB CIUDAD JARDIN MAÑONGO NAGUANAGUA."
        ),
        "city": "VALENCIA",
    },
    {
        "company_name": "YUMMY RIDES, C.A.",
        "email": "claudhia.castillo@yummysuperapp.com",
        "rif": "J-60301732-6",
        "contact_name": "CLAUDHIA CASTILLO",
        "representative_name": "EUBRYS COROMOTO ROJAS TORRES",
        "representative_id_number": "V-17.311.805",
        "phone": "58 414 2673185",
        "address": (
            "AV LA ESTANCIA EDIF CENTRO BENAVEN, TORRE A PISO 7 OF A-71 "
            "URB CHUAO CARACAS (CHACAO) MIRANDA."
        ),
        "city": "CARACAS",
    },
    {
        "company_name": "HEJ MODE V77, C.A.",
        "email": "daniela.romero@holamoda.net",
        "rif": "J-50584568-3",
        "contact_name": "DANIELA ROMERO",
        "representative_name": "ANTONIO DOUMET",
        "representative_id_number": "V-12.073.528",
        "phone": "58 424 2063998",
        "address": (
            "AV LIBERTADOR Y LA AUTOPISTA FRANCIASCO FAJARDO CCCENTRO SAMBIL "
            "NIVEL LIBERTADOR LOCAL COMERCIAL DISTIGUIDOS  CON LOS NROS L-R36, "
            "L-R38, L-R39 Y L-R40 SECTOR CHACAOCARACAS  MIRANDA ZONA POSTAL 1061"
        ),
        "city": "",
    },
    {
        "company_name": "GH ESTETICA, C.A",
        "email": "raiza.diaz@ghestetica.com",
        "rif": "J-50072870-0",
        "contact_name": "RAIZA DIAZ",
        "representative_name": "DILMAR LISSETH HERNANDEZ RIOS",
        "representative_id_number": "V-18.411.201",
        "phone": "58 4127478883",
        "address": (
            "AV PRINCIPAL EDIF CLINICA I.E.Q PISO 9 LOCAL CONSULTORIOS 9-6, "
            "9-7 Y 9-8 URB LOS MANGO VALENCIA CARABOBO"
        ),
        "city": "VALENCIA",
    },
]

_HISTORICAL_RIFS = [row["rif"] for row in _SAMBIL_HISTORICAL_CLIENTS]


def _normalize_email(value: str) -> str:
    s = (value or "").strip()
    if len(s) >= 2 and s[0] == s[-1] == "'":
        s = s[1:-1].strip()
    return s


def forwards(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    Client = apps.get_model("clients", "Client")

    workspace = Workspace.objects.filter(slug=SAMBIL_WORKSPACE_SLUG).first()
    if workspace is None:
        return

    for row in _SAMBIL_HISTORICAL_CLIENTS:
        rif = (row["rif"] or "").strip()
        if not rif:
            continue
        Client.objects.get_or_create(
            workspace_id=workspace.id,
            rif=rif,
            defaults={
                "company_name": (row["company_name"] or "").strip(),
                "email": _normalize_email(row["email"]),
                "contact_name": (row["contact_name"] or "").strip(),
                "representative_name": (row["representative_name"] or "").strip(),
                "representative_id_number": (
                    row["representative_id_number"] or ""
                ).strip(),
                "phone": (row["phone"] or "").strip()[:32],
                "address": (row["address"] or "").strip(),
                "city": (row["city"] or "").strip(),
                "notes": HISTORICAL_NOTES,
                "status": "active",
                "is_active": True,
            },
        )


def backwards(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    Client = apps.get_model("clients", "Client")

    workspace = Workspace.objects.filter(slug=SAMBIL_WORKSPACE_SLUG).first()
    if workspace is None:
        return

    Client.objects.filter(
        workspace_id=workspace.id,
        rif__in=_HISTORICAL_RIFS,
        notes=HISTORICAL_NOTES,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0004_alter_clientbrand_created_at_and_more"),
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
