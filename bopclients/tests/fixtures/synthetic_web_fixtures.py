"""Synthetic web search response fixtures for offline P30.5G.4A testing.

GUARANTEE: 100% synthetic in-memory fixtures. No real API calls, no real search index data,
no persistent external corpora.
"""

from typing import Dict, Any


SYNTHETIC_BRAVE_FIXTURES: Dict[str, Dict[str, Any]] = {
    # 1. Cardiology Query
    "sociedad colombiana de cardiología cali": {
        "query": {
            "original": "Sociedad Colombiana de Cardiología Cali",
            "more_results_available": False,
        },
        "web": {
            "results": [
                {
                    "title": "Sociedad Colombiana de Cardiología y Cirugía Cardiovascular | Inicio",
                    "url": "https://scc.org.co",
                    "description": "Asociación médica y científica de derecho privado que agrupa a los médicos cardiólogos y cirujanos cardiovasculares de Colombia con capítulo Valle del Cauca.",
                },
                {
                    "title": "Clínica de la Asociación Médica de Cardiología",
                    "url": "https://clinicaasociacioncardiologia.com",
                    "description": "Centro hospitalario y clínica privada con urgencias 24 horas y hospitalización en Cali.",
                },
                {
                    "title": "Equipos Médicos Cardiovasculares S.A.S.",
                    "url": "https://equiposcardio.com.co",
                    "description": "Distribución y venta de tecnología médica para laboratorios y hospitales en Colombia.",
                },
            ]
        },
    },

    # 2. Urology Query
    "sociedad colombiana de urología cali": {
        "query": {
            "original": "Sociedad Colombiana de Urología Cali",
            "more_results_available": False,
        },
        "web": {
            "results": [
                {
                    "title": "Sociedad Colombiana de Urología - SCU",
                    "url": "https://scu.org.co",
                    "description": "Sociedad científica sin ánimo de lucro que congrega a los especialistas en urología de Colombia con sede nacional y actividades en Cali y el Valle.",
                },
                {
                    "title": "Consultorio Urológico Especializado Dr. Gómez",
                    "url": "https://consultoriourologicocali.com",
                    "description": "Consulta médica particular de urología en el Edificio de Colores, Cali.",
                },
            ]
        },
    },

    # 3. Endocrinology Query
    "asociación colombiana de endocrinología colombia": {
        "query": {
            "original": "Asociación Colombiana de Endocrinología Colombia",
            "more_results_available": False,
        },
        "web": {
            "results": [
                {
                    "title": "Asociación Colombiana de Endocrinología, Diabetes y Metabolismo",
                    "url": "https://endocrino.org.co",
                    "description": "Sociedad médica y científica nacional que lidera la investigación y educación médica continuada en endocrinología en Colombia.",
                },
                {
                    "title": "Farmacia Dermatológica y Endocrina del Valle",
                    "url": "https://farmaciaendocrinadelvalle.com",
                    "description": "Venta de medicamentos formulados y fórmulas magistrales en Cali.",
                },
            ]
        },
    },

    # 4. Pediatrics Query
    "sociedad colombiana de pediatría valle del cauca": {
        "query": {
            "original": "Sociedad Colombiana de Pediatría Valle del Cauca",
            "more_results_available": False,
        },
        "web": {
            "results": [
                {
                    "title": "Sociedad Colombiana de Pediatría - Regional Valle del Cauca",
                    "url": "https://scpvalle.com",
                    "description": "Gremio y sociedad científica pediátrica de profesionales de la salud dedicados a la infancia en el Valle del Cauca y Cali.",
                },
                {
                    "title": "Sociedad Colombiana de Pediatría | Nacional",
                    "url": "https://scp.com.co",
                    "description": "Federación y sociedad científica que reúne a los médicos pediatras a nivel nacional en Colombia.",
                },
                {
                    "title": "Hospital Pediátrico Infantil San José",
                    "url": "https://hospitalpediatricosanjose.org",
                    "description": "Hospital de tercer nivel de atención pediátrica especializada y cuidados intensivos.",
                },
            ]
        },
    },

    # 5. Obstetrics & Gynecology Query
    "federación colombiana de obstetricia y ginecología colombia": {
        "query": {
            "original": "Federación Colombiana de Obstetricia y Ginecología Colombia",
            "more_results_available": False,
        },
        "web": {
            "results": [
                {
                    "title": "Federación Colombiana de Obstetricia y Ginecología - FECOLSOG",
                    "url": "https://fecolsog.org",
                    "description": "Organización gremial nacional sin ánimo de lucro que reúne a las asociaciones y sociedades de obstetricia y ginecología de Colombia.",
                },
                {
                    "title": "Colegio Médico del Valle",
                    "url": "https://colegiomedicovalle.org",
                    "description": "Colegio profesional de médicos del departamento del Valle del Cauca con sede en Cali.",
                },
            ]
        },
    },
}
