// SPDX-License-Identifier: GPL-3.0-only
namespace Example;

/// <summary>A strongly typed value. Handles literal {braces}, pipes | and &lt;angles&gt;.</summary>
/// <typeparam name="T">The value type.</typeparam>
public sealed class Value<T> : IParsable<Value<T>>
{
    /// <summary>Reads a value.</summary>
    public void Read() { }

    /// <summary>Reads a named value.</summary>
    /// <param name="name">The name to read.</param>
    public void Read(string? name) { }

    /// <inheritdoc />
    public static Value<T> Parse(string s, IFormatProvider? provider) => new();

    /// <inheritdoc />
    public static bool TryParse(string? s, IFormatProvider? provider, out Value<T> result)
    {
        result = new();
        return true;
    }

    /// <summary>A nested value.</summary>
    public sealed class Nested { }
}
