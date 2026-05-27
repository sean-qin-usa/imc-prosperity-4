sweetRyce — 1:52 PM
ranking doesn't matter so this isn't necessarily the case
sweetRyce — 1:53 PM
Wait idk where to find the stats
that's the only thing
I want to find it lMAO
bimbambom6100 — 1:53 PM
wdym they released it when round 2 results were released
is it unavailable now?
sweetRyce — 1:54 PM
huh. where.
Elastic Collider — 2:07 PM
in the manual round, we are only trading agaisnt the imc bots ( counter parties) right? no game theory between the human participants (us) right?
i mean the average is not using the bids we all submit right, its using the bots prices
Jackafett — 2:07 PM
No it’s using our bids
Elastic Collider — 2:08 PM
oh so we are competing agaisnt each other again like in round 2?
imc likes sow discord bw the players
Divistical — 2:21 PM
does average bid of the other players use both the low and high bid?
A.R.I.A.
APP
 — 2:31 PM

djkorou360. has been warned
Reason: Posted an invite
Abd — 2:31 PM
just b2
Smile — 2:35 PM
What if reserve price come as 920 
A.R.I.A.
APP
 — 2:50 PM

djkorou360. has been warned
Reason: Posted an invite
Meatballsforever — 2:58 PM
so the first bid seems to be unaffected by other players, as far as I understand it. it
rubdubz — 2:59 PM
isnt 751 wrong for b1 i swear that not optimal
BoxingSnail3808 — 3:01 PM
think it depends on what you choose for b2
Meatballsforever — 3:03 PM
right
Sofian [M.AI],  — 3:04 PM
Does our bid have to be a multiple of 5?
Meatballsforever — 3:05 PM
no, the reserve prices are
check the wiki it's rly helpful for the manual
Sofian [M.AI],  — 3:06 PM
thx
Pokeking2 — 3:12 PM
Slightly confused by the PNL penalisation. Is it applied to your total PNL (so the amount earned from your first bid and second bid) or just the money from the second bid.
Meatballsforever — 3:18 PM
oh that's a really good point
ambiguous wording
Purrs — 3:22 PM
So, what are we thinking for B2? Gonna poll the crowd lol
Firefly — 3:24 PM
@Synthia_Admin Any clarifications?
johnny [HOT],  — 3:28 PM
" If the first bid is higher than the reserve price, they trade with you at your first bid."

is it only filled if b1 > r or b1 >= r
Michael Parker — 3:31 PM
Does manual ever get to be live trading?
April ⬅️ not a guy — 3:32 PM
No
Do you mean
Day trading
Manual lol
Michael Parker — 3:33 PM
Asking if we acc go live w a real order book lmao
Martar — 3:34 PM
Hi, just wanted to clarify a couple of details about the manual round:

The statement says “the distribution of the bids is uniformly distributed at increments of 5 between 670 and 920”. Could you confirm whether this actually refers to counterparties’ reserve prices being uniformly distributed over {670, 675, ..., 920}, rather than players’ bids?

When trading with a counterparty, does each successful trade correspond to exactly one unit of the good, or can a single counterparty provide multiple units?

Thanks! 
Martar — 3:35 PM
The question is how many goods we trade with each counterparty
Martar — 3:36 PM
@Tomas
Meatballsforever — 3:41 PM
confused by this:  "the chance of a trade rapidly decreases: you will trade at your second bid but your PNL is penalised by..." uhhh so how is the chance of the trade decreasing at all? and is this PnL talking about our total pnl or what?
johnny [HOT],  — 3:50 PM
" If the first bid is higher than the reserve price, they trade with you at your first bid."

is it only filled if b1 > r or b1 >= r
 [HOT], 
Meatballsforever — 3:52 PM
They specify “lower or equal to” later so it must be a strict thing
johnny [HOT],  — 3:53 PM
thats for the b2 though
Meatballsforever — 3:53 PM
Sure… but I think the wording implies that higher means strictly higher
 [HOT], 
Abd — 3:57 PM
If b1>r and b2>=r then b1+b2 > r ?
Im just typing
Chennethelius — 4:00 PM
aren't you only getting filled at one order?
a3d1m — 4:03 PM
I thought you were getting filled some volume for the first one and then some set volume for the second
Abd — 4:04 PM
Day trading is valid
Ik someone who makes 200k a day from day trading
For every + ev day trader there r 5000 -ev day traders who become broke by the end of the first week
If anyone wants to dispute this claim, feel free to do so
Hugo — 4:11 PM
is it that the only thing affecting wether b1 being filled is if its above reserve and no other teams actions will affect your b1 outcome?
Rogacz — 4:16 PM
Is the first bid independent of the second?
Abd — 4:17 PM
Optimal second bid determines first bid but yeah
Rogacz — 4:19 PM
I am confused by this:
If the first bid is higher than the reserve price, they trade with you at your first bid. If your second bid is higher than the reserve price of a counterparty and higher than the mean of second bids of all players you trade at your second bid.

What if both statements are true? Can a counterparty trade with me on both prices?
Camzzer — 4:29 PM
guys, in the wiki higher is > or >=
like if i bid 765 does it fit with 765 or i need to bid 766
Jonty — 4:31 PM
>
cuitin — 4:31 PM
specifically where it says "If the first bid is higher than the reserve price" for example, does it mean greater than or equal to, or just greater than
cuitin — 4:31 PM
ah ok ty
April ⬅️ not a guy — 4:36 PM
so true pookie
pickle_monster — 4:41 PM
For bid 1, will my bid always be accepted for those whose reserve price is lower? Or is it like other bots are also placing bids to each other and I have to be the lowest one out of the bots that exceeds the seller's reserve price? 
Camzzer — 4:47 PM
how do you know it ?
Jonty — 4:47 PM
they clarified earlier
Abd — 5:08 PM
Higher means >
Atleast means >=
That's the professional wording
estella — 5:26 PM
How do you guys think about the second bid
Meatballsforever — 5:26 PM
if you go lower than the average, you are in trouble
so don't do that
a3d1m — 5:33 PM
If you go much higher theres not that much of a gain anyway
Meatballsforever — 5:35 PM
Still not clear on if the pnl multiplier is for all your pnl or for pnl from the second bid
The wording is kinda sus
a3d1m — 5:36 PM
I would asssume its just pnl gained from the trades that happen on 2nd bid
Enrico Berto — 5:36 PM
I've seen this question a million times at least
Meatballsforever — 5:37 PM
Oh cool, have you seen an answer? Lol
stqrri — 5:37 PM
second
Enrico Berto — 5:37 PM
weird that admin never posted the solution on announcements
Enrico Berto — 5:37 PM
second only
stqrri — 5:37 PM
Forwarded
If you first bid is already higher than a certain counterparties reserve price, you just trade it at that level (first bid), and then sell it at fair price later. 2nd bid is not even considered in that case.

Counterparties are not other players, but predefined bots, with their reserve prices distributed according to distribution on Wiki

Other player's 2nd bids do impact average of 2nd bids, and then the scaling formula applies (if you're below it)
#manual-trading  •  6:23 AM
Abd — 5:44 PM
So like what are we putting
866? 851? 860?
a3d1m — 5:45 PM
805 second bid
Fearmongering has to stop everyone lower your high bids
stqrri — 5:59 PM
im losing my mind doing this
Mewmew — 6:02 PM
Anyone used claude and got 1 L  pnl?
K_Tesla — 6:04 PM
"The distribution of the bids is uniformly distributed at increments of 5 between 670 and 920 (inclusive on both ends).".

So only 670, 675, 680, 685, 690,..., 910, 915, 920 are chosen??
ThatObiGuy — 6:12 PM
do you know who?
AX2k — 6:19 PM
so there’s at most one counterparty at each reserve price?
if they were gonna say something like this why be vague abt the number of counterparties
stqrri — 6:21 PM
it does not matter how many counterparties there are
i dont understand why it matters
they are uniformly distributed
that is all that matters
a3d1m — 6:21 PM
what does mean seem like for unprepared teams
stqrri — 6:22 PM
i guess it matters if you are trying to see how much risk to take this round, but i think itd be reasonable to guess that total max pnl will be similar to previous rounds and previous years 
∆50||NO∆H — 6:25 PM
Is the ongoing discussion on 2nd bid