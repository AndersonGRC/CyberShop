# validators.py
import re
from datetime import datetime
from flask import jsonify

class PSEValidator:
    @staticmethod
    def validate_payment_data(data):
        required_fields = {
            'amount': (float, lambda x: x > 0),
            'financialInstitutionCode': (str, lambda x: x.isdigit() and len(x) == 4),
            'userType': (str, lambda x: x in ['N', 'J']),
            'pseReference2': (str, lambda x: x in ['CC', 'CE', 'NIT', 'TI', 'PP']),
            'pseReference3': (str, lambda x: x.isdigit() and 5 <= len(x) <= 20),
            'buyerFullName': (str, lambda x: 3 <= len(x) <= 100),
            'buyerEmail': (str, lambda x: re.match(r"[^@]+@[^@]+\.[^@]+", x)),
            'buyerPhone': (str, lambda x: re.match(r"^[0-9]{10,15}$", x))
        }

        errors = []
        
        # Validar campos requeridos
        for field, (field_type, validator) in required_fields.items():
            if field not in data:
                errors.append(f"Campo requerido faltante: {field}")
                continue
                
            try:
                # Validar tipo de dato
                if not isinstance(data[field], field_type):
                    data[field] = field_type(data[field])
                
                # Validar valor específico
                if not validator(data[field]):
                    errors.append(f"Valor inválido para {field}")
            except (ValueError, TypeError):
                errors.append(f"Tipo de dato inválido para {field}")

        if errors:
            return False, errors
        
        return True, data