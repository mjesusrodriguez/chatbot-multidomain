import pandas as pd
import matplotlib.pyplot as plt

#Read JSON data into a pandas DataFrame
snips_df = pd.read_json("input/snips/snips.json")
snips_df.columns = ["text", "intent"]


#Plot class distribution

plt.figure(figsize=(15,15))
fig, axs = plt.subplots(1,2)
plt.subplots_adjust(right = 1.7)
grouped = snips_df.groupby("intent").count().reset_index()
axs[0].barh(grouped["intent"], grouped["text"])
axs[0].set_xlabel("count")
axs[1].pie(grouped["text"], labels=grouped["intent"], startangle=90, autopct='%1.1f%%')
axs[1].axis('equal')
plt.show()