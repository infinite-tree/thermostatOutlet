# Thermostat Based Heater Control

Turn on and off outlets that drive heaters based on the temperature. 

## Problem
Greenhouses leak heat like a linen shirt in the Artic. Heating them works a little differently than heating a building that maintains temp. Instead of heating cycles followed by rest periods, its about matching the heat being produce to the heat being lost. 

This controller hope to solve that problem for a 3,000 sqft greenhouse using 3 forced air diesel heaters.

## Status
Experimental yet mission critical


## Installation

```
sudo cp outlet.service /etc/systemd/system/multi-user.target.wants/
sudo systemctl enable outlet.service
sudo systemctl start outlet.service
```

