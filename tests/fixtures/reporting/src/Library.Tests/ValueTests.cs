using System;
using NUnit.Framework;

namespace Library.Tests;

public sealed class ValueTests
{
    [TestCase(false, 1)]
    [TestCase(true, 2)]
    public void Choose(bool flag, int expected)
    {
        if (Value.Choose(flag) != expected)
        {
            throw new InvalidOperationException("Incorrect choice.");
        }
    }

    [Test]
    public void ConfigurableFailure()
    {
        if (Environment.GetEnvironmentVariable("REPORTING_FAIL") == "true")
        {
            throw new InvalidOperationException("Example failure for the reporter.");
        }
    }

    [Test, Ignore("Example skipped test.")]
    public void Skipped() { }
}
