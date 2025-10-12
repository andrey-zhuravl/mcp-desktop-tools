"""Template utilities and built-in template registry."""

from .registry import TemplateDefinition, TemplateRegistry, TemplateRegistryError, load_registry

__all__ = [
    "TemplateDefinition",
    "TemplateRegistry",
    "TemplateRegistryError",
    "load_registry",
]
