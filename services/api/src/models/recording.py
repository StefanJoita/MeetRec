#/services/api/src/models/recording.py
#===================================================================
#Modelul Recording - mapeaza tabela "recordings" din PostgreSQL
#Fiecare atribut al clasei = o coloana in tabela
#Tipurile python sunt mapate automat la tipuri SQL:
#str - varchar
#int - integer
#datetime - timestamptz
#bool - boolean
#dict (json) - jsonb
#====================================================================

import uuid 
from datetime import datetime, date, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, BigInteger, Date, Text
from sqlalchemy import TIMESTAMP, Enum as SAEnum, JSON, SmallInteger
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.models.base import base

#Enumurile din Python - sincronizate cu enumurile din init.sql