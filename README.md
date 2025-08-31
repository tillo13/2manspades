# Two-Man Spades

A web-based implementation of the classic card game Spades, adapted for two players with custom scoring rules.

## Play Now

**🎮 [Play at 2manspades.com](https://2manspades.com)**

## Game Overview

Two-Man Spades is a trick-taking card game played between you (Tom) and the computer opponent (Marta). Each hand consists of dealing 11 cards to each player, with one card discarded before bidding and playing 10 tricks.

## Rules Summary

### Setup
- Each player receives 11 cards
- Players are randomly assigned **Even** or **Odd** parity at game start
- The player with **Odd** parity leads the first trick of the game
- Leadership alternates each hand

### Phases

#### 1. Discard Phase
- Both players discard one card face-down
- Cards discarded form the "discard pile" for bonus scoring

#### 2. Bidding Phase
- Players bid how many tricks they expect to take (0-10)
- **Nil Bid (0)**: Attempt to take zero tricks
  - Success: +100 points
  - Failure: -100 points + bag penalties
- **Blind Bidding**: Available when 100+ points behind
  - Must bid 5-10 tricks before seeing your hand
  - **Double** points and penalties
- Computer opponent uses advanced AI bidding strategy

#### 3. Playing Phase
- Play 10 tricks with remaining cards
- Must follow suit if possible
- Spades are trump (beat all other suits)
- Cannot lead spades until "broken" (spades played on a trick)

### Scoring System

#### Basic Scoring
- **Make your bid**: Bid × 10 points
- **Fail your bid**: -(Bid × 10) points
- **Overtricks ("Bags")**: No immediate points, but create penalties

#### Bags System
- Extra tricks beyond your bid = bags
- **Penalty**: Every 7 bags = -100 points
- **Bonus**: Every 5 negative bags = +100 points
- Bags appear in the "ones column" of your score display

#### Discard Pile Scoring
- Values: A=1, 2-10=face value, J=11, Q=12, K=13
- Add both discarded card values
- **Even total**: Even-parity player gets bonus points
- **Odd total**: Odd-parity player gets bonus points
- **Normal bonus**: 10 points
- **Double bonus**: 20 points (same suit OR same rank)

#### Special Cards
- **7 of Diamonds**: Reduces winner's bags by 2
- **10 of Clubs**: Reduces winner's bags by 1
- These work in both discard pile and trick wins

#### Blind Bidding
- Available when 100+ points behind opponent
- Must bid 5-10 tricks
- All scoring is **doubled** (points and penalties)

### Winning
- First to **300 points** wins
- **Mercy rule**: 300+ point lead ends game immediately

## Technical Features

- **Responsive design** works on mobile and desktop
- **Real-time scoring** with floating score displays
- **Advanced computer AI** with intelligent bidding and play
- **Hand history** and detailed scoring breakdowns
- **Debug mode** for development (hidden in production)

## Development

Built with:
- **Backend**: Python Flask
- **Frontend**: Vanilla JavaScript + CSS
- **Deployment**: Google App Engine
- **AI Logic**: Custom algorithms for computer strategy

The game features sophisticated computer AI that:
- Analyzes hand strength for bidding
- Considers parity assignments and game state
- Avoids bag penalties when ahead
- Uses blind bidding strategically when behind
- Protects special cards during play

---

**🃏 [Start Playing Now](https://2manspades.com)**