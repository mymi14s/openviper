from typing import Any

from openviper.template.environment import get_jinja2_env, get_template_directories


def render_to_string(template_name: str, context: dict[str, Any] | None = None) -> str:
    """Render a template to a string.

    Automatically resolves template search paths from ``settings.TEMPLATES_DIR``
    and ``templates/`` folders in ``settings.INSTALLED_APPS``.

    Args:
        template_name: Name of the template to render.
        context: Optional dictionary of context variables.

    Returns:
        The rendered template as a string.
    """
    search_paths = get_template_directories()
    env = get_jinja2_env(search_paths)
    template = env.get_template(template_name)
    return template.render(**(context or {}))
