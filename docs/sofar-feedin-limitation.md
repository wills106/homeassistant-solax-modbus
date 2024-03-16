# Sofar Feed-In Limitation

Controls, whether power can be fed-in to the grid. Using the limitation mode you can control how the power limitation is calculated

Set "FeedIn: Limitation Mode" to one of the following values:

- **Disabled**: Reflux control is disabled. Excess power will always be fed-in to the grid.
- **Enabled - Feed-in limitation**: The sum of the feeding-in phases must not exceed the set power limitation value. The power of phases drawing power from the grid is disregarded here.
- **Enabled - 3-phase limit**: The sum of the feed-in power of all three phases must not exceed the set power limit value. This setting is suitable for balancing metering, as is common in Germany, for example.

After changing either "FeedIn: Limitation Mode" and/or "FeedIn: Maximum Power" press "FeedIn: Update" to commit the values to the inverter.