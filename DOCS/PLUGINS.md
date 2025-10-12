# Plugins

The MCP Desktop Tools runtime supports a lightweight plugin system that can load
extensions from Python entry points and from directories on disk. Plugins are
expected to expose a callable ``register(plugin_api)`` that receives an instance
of :class:`mcp_desktop_tools.plugins.api.PluginAPI` and use it to register tool
handlers.

## Manifest

Each filesystem plugin must provide a ``plugin.yaml`` manifest with the
following fields:

```yaml
id: demo.echo
name: Demo Echo
version: 0.1.0
entry: examples.plugins.demo_plugin.main:register
capabilities:
  - read_only
```

The loader validates manifests against the built-in schema checks and enforces
the security policy before executing plugin code.

## Discovery

Plugins are discovered using two mechanisms:

* ``setuptools`` entry points exposed via the ``mcp_desktop_tools.plugins``
  group.
* Directories containing ``plugin.yaml`` inside ``~/.mcpdt/plugins`` or the
  local ``./plugins`` directory. The location can be overridden with the
  ``MCPDT_PLUGINS_DIR`` environment variable.

## Policy

The default policy requires the ``read_only`` capability and honours
allow/deny-lists through the ``MCPDT_PLUGINS_ALLOW`` and ``MCPDT_PLUGINS_DENY``
variables. A plugin whose identifier is deny-listed or not present in the allow
list is blocked and surfaced via the introspection tooling.

## Registering Tools

During registration a plugin can call ``api.register_tool(name, handler)`` to
publish handlers. Duplicate tool names raise a
:class:`mcp_desktop_tools.plugins.api.PluginRegistrationError`.

See ``examples/plugins/demo_plugin`` for a minimal implementation.
