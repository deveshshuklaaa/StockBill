"""Typed dynamic-attribute validation and persistence for the product catalogue."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import serializers

from .models import (
    AttributeChoice,
    AttributeDefinition,
    Category,
    CategoryAttribute,
    ProductAttributeValue,
)

MAX_TEXT_LENGTH = 500
MAX_CODE_LENGTH = 50
CODE_PATTERN = r"^[a-z0-9]+(?:_[a-z0-9]+)*$"


class AttributeServiceError(serializers.ValidationError):
    """Validation error carrying attribute-specific messages."""


def _get_category(category_id):
    if category_id is None:
        return None
    try:
        return Category.objects.get(pk=category_id)
    except Category.DoesNotExist:
        raise AttributeServiceError({"catalogue_category": ["Category not found."]})


def get_category_schema(category):
    """Return the ordered form schema for a category's active assigned attributes."""
    if category is None:
        return []
    assignments = (
        CategoryAttribute.objects.filter(
            category=category, attribute_definition__is_active=True
        )
        .select_related("attribute_definition")
        .prefetch_related("attribute_definition__choices")
    )
    schema = []
    for assignment in assignments:
        definition = assignment.attribute_definition
        schema.append(
            {
                "code": definition.code,
                "name": definition.name,
                "data_type": definition.data_type,
                "unit": definition.unit or None,
                "decimal_places": definition.decimal_places,
                "is_required": assignment.is_required,
                "is_filterable": assignment.is_filterable,
                "is_invoice_visible": assignment.is_invoice_visible,
                "display_order": assignment.display_order,
                "choices": [
                    {"value": choice.value, "label": choice.label}
                    for choice in definition.choices.all()
                ]
                if definition.data_type == AttributeDefinition.TYPE_CHOICE
                else [],
            }
        )
    return schema


def validate_and_normalize_attributes(category, submitted, *, current_product=None):
    """Validate a submitted {code: value} dict against a category's schema.

    Returns the list of validated (attribute_definition, typed_value) tuples.
    Raises AttributeServiceError on any rule violation.
    """
    errors = {}
    if category is None:
        if submitted:
            raise AttributeServiceError(
                {"attributes": ["Attributes require a catalogue category."]}
            )
        return []

    assignments = CategoryAttribute.objects.filter(
        category=category, attribute_definition__is_active=True
    ).select_related("attribute_definition")
    definitions = {a.attribute_definition.code: a for a in assignments}

    unknown = set(submitted or {}) - set(definitions)
    if unknown:
        errors["attributes"] = [
            f"Attribute '{code}' is not assigned to category '{category.name}'."
            for code in sorted(unknown)
        ]

    validated = []
    submitted = submitted or {}
    for code, assignment in definitions.items():
        definition = assignment.attribute_definition
        if code in unknown:
            continue
        if code not in submitted:
            if assignment.is_required and not (
                current_product
                and ProductAttributeValue.objects.filter(
                    product=current_product, attribute_definition=definition
                ).exists()
            ):
                errors.setdefault("attributes", []).append(
                    f"Attribute '{code}' is required for category '{category.name}'."
                )
            continue
        raw = submitted[code]
        if raw is None or raw == "":
            if assignment.is_required:
                errors.setdefault("attributes", []).append(
                    f"Attribute '{code}' is required for category '{category.name}'."
                )
            continue
        try:
            typed = _coerce_typed_value(definition, raw)
        except AttributeServiceError as exc:
            detail = (
                exc.detail["attributes"] if isinstance(exc.detail, dict) else exc.detail
            )
            errors.setdefault("attributes", []).extend(
                detail if isinstance(detail, list) else [str(detail)]
            )
            continue
        validated.append((definition, typed))

    if errors:
        raise AttributeServiceError({"attributes": errors.get("attributes", [])})
    return validated


def _coerce_typed_value(definition, raw):
    data_type = definition.data_type
    try:
        if data_type == AttributeDefinition.TYPE_TEXT:
            text = str(raw).strip()
            if not text:
                raise AttributeServiceError(
                    {
                        "attributes": [
                            f"Attribute '{definition.code}' must not be empty."
                        ]
                    }
                )
            if len(text) > MAX_TEXT_LENGTH:
                raise AttributeServiceError(
                    {
                        "attributes": [
                            f"Attribute '{definition.code}' exceeds {MAX_TEXT_LENGTH} characters."
                        ]
                    }
                )
            return text

        if data_type == AttributeDefinition.TYPE_INTEGER:
            if isinstance(raw, bool) or not isinstance(raw, (int, str)):
                raise AttributeServiceError(
                    {
                        "attributes": [
                            f"Attribute '{definition.code}' must be a whole number."
                        ]
                    }
                )
            value = int(str(raw).strip())
            return value

        if data_type == AttributeDefinition.TYPE_DECIMAL:
            if isinstance(raw, bool):
                raise AttributeServiceError(
                    {"attributes": [f"Attribute '{definition.code}' must be a number."]}
                )
            value = Decimal(str(raw).strip())
            if not value.is_finite():
                raise AttributeServiceError(
                    {"attributes": [f"Attribute '{definition.code}' must be a number."]}
                )
            if definition.decimal_places is not None:
                quantum = Decimal(1).scaleb(-definition.decimal_places)
                if value != value.quantize(quantum):
                    raise AttributeServiceError(
                        {
                            "attributes": [
                                f"Attribute '{definition.code}' exceeds {definition.decimal_places} decimal places."
                            ]
                        }
                    )
            return value

        if data_type == AttributeDefinition.TYPE_BOOLEAN:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"true", "1", "yes"}:
                    return True
                if lowered in {"false", "0", "no"}:
                    return False
            raise AttributeServiceError(
                {
                    "attributes": [
                        f"Attribute '{definition.code}' must be true or false."
                    ]
                }
            )

        if data_type == AttributeDefinition.TYPE_DATE:
            from datetime import date

            if isinstance(raw, date):
                return raw
            return date.fromisoformat(str(raw).strip())

        if data_type == AttributeDefinition.TYPE_CHOICE:
            raw_value = str(raw).strip()
            choice = AttributeChoice.objects.filter(
                attribute_definition=definition, value=raw_value
            ).first()
            if choice is None:
                allowed = list(definition.choices.values_list("value", flat=True))
                raise AttributeServiceError(
                    {
                        "attributes": [
                            f"Attribute '{definition.code}' must be one of: {', '.join(allowed)}."
                        ]
                    }
                )
            return choice

    except (ValueError, TypeError, InvalidOperation):
        raise AttributeServiceError(
            {
                "attributes": [
                    f"Attribute '{definition.code}' has an invalid {data_type.lower()} value."
                ]
            }
        )
    raise AttributeServiceError(
        {"attributes": [f"Unsupported data type '{data_type}'."]}
    )


@transaction.atomic
def apply_product_attributes(*, product, validated):
    """Replace the product's dynamic attribute values with the validated set.

    Attribute/value changes never touch inventory, pricing, tax, or billing data.
    """
    existing = list(product.attribute_values.select_for_update().all())
    definitions = {definition for definition, _ in validated}
    for value in existing:
        if value.attribute_definition not in definitions:
            value._allow_service_update = True
            value.delete()
    for definition, typed_value in validated:
        ProductAttributeValue.objects.filter(
            product=product, attribute_definition=definition
        ).delete()
        ProductAttributeValue.objects.create(
            product=product,
            attribute_definition=definition,
            value_text=typed_value
            if definition.data_type == AttributeDefinition.TYPE_TEXT
            else None,
            value_integer=typed_value
            if definition.data_type == AttributeDefinition.TYPE_INTEGER
            else None,
            value_number=typed_value
            if definition.data_type == AttributeDefinition.TYPE_DECIMAL
            else None,
            value_boolean=typed_value
            if definition.data_type == AttributeDefinition.TYPE_BOOLEAN
            else None,
            value_date=typed_value
            if definition.data_type == AttributeDefinition.TYPE_DATE
            else None,
            value_choice=typed_value
            if definition.data_type == AttributeDefinition.TYPE_CHOICE
            else None,
        )


def assemble_product_attributes(product):
    """Return {code: typed_value} for a product's dynamic attributes."""
    values = product.attribute_values.select_related(
        "attribute_definition", "value_choice"
    ).all()
    return {v.attribute_definition.code: v.typed_value() for v in values}
