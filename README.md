# 🤖 Professional Telegram Affiliate Bot with AI

<div align="center">

[![License](https://img.shields.io/badge/License-Proprietary-blue.svg)](https://doublegram.com/marketplace/affiliate)
[![Platform](https://img.shields.io/badge/Platform-Telegram-blue.svg)](https://telegram.org/)
[![AI](https://img.shields.io/badge/AI-OpenAI%20Integration-green.svg)](https://openai.com/)
[![Self-Hosted](https://img.shields.io/badge/Hosting-Self--Hosted-orange.svg)](#)
[![Language](https://img.shields.io/badge/Language-Python-yellow.svg)](https://python.org/)

**The first and only self-hosted Telegram bot for Amazon affiliate marketing with integrated AI**

*Transform your affiliate marketing with automated, AI-powered content generation and multi-channel publishing*

[🚀 Get License Now](https://doublegram.com/marketplace/affiliate) • [💬 Support](#support)

</div>
---

## ✨ **Why This Bot Changes Everything**

### 🎯 **The Problem with Current Solutions:**
- 🔴 **Shared Resources**: Other bots serve hundreds of users → slow performance
- 🔴 **Monthly Fees**: $15-50/month = $180-600/year recurring costs
- 🔴 **Limited AI**: Basic templates, no real AI content generation
- 🔴 **No Control**: Closed source, vendor lock-in, data privacy concerns
- 🔴 **Feature Limits**: Restricted products, channels, customization

### ✅ **Our Solution:**
- 🟢 **100% Self-Hosted**: Your server, your performance, zero sharing
- 🟢 **Lifetime License**: €79 once, own it forever
- 🟢 **Advanced AI**: Full OpenAI integration with custom prompts
- 🟢 **Open Source**: See the code, trust the process
- 🟢 **Unlimited Everything**: Products, channels, categories, admins

---

## 🚀 **Key Features**

### 🤖 **AI-Powered Content Generation**
- **OpenAI Integration**: Use your own API key for complete control
- **Custom Prompts**: Tailor AI responses to your brand voice
- **Professional Posts**: Automatically generated, engaging content
- **Multiple Languages**: Full internationalization support

### 📢 **Multi-Channel Publishing**
- **Automated Publishing**: From approval to live posts in seconds
- **Category-Based Routing**: Each category → dedicated channel/group
- **Smart Approval System**: Manual review or full automation
- **Bulk Operations**: Manage hundreds of products effortlessly

### 🏠 **Self-Hosted Excellence**
- **Zero Dependencies**: No shared resources or rate limits
- **Maximum Privacy**: Your data never leaves your server
- **Custom Modifications**: Open source = unlimited customization
- **Enterprise Security**: Bank-level data protection

### ⚙️ **Advanced Management**
- **Multi-Admin Support**: Team collaboration with role management
- **Automated Price Monitoring**: Cronjobs track price changes
- **Smart Link Management**: Automatic affiliate tag injection
- **Comprehensive Analytics**: Track performance and engagement

---

## 🏆 **Competitive Comparison**

| Feature | Our Bot | Competitor A | Competitor B | DIY Solution |
|---------|---------|--------------|--------------|--------------|
| **Hosting** | 🟢 Self-hosted | 🔴 Shared cloud | 🔴 Shared cloud | 🟡 Complex setup |
| **AI Integration** | 🟢 Full OpenAI | 🔴 Basic templates | 🔴 No AI | 🔴 Manual coding |
| **Pricing** | 🟢 €79 lifetime | 🔴 $25-50/month | 🔴 $15-30/month | 🔴 Development costs |
| **Source Code** | 🟢 Open source | 🔴 Closed | 🔴 Closed | 🟡 From scratch |
| **Performance** | 🟢 Dedicated | 🔴 Shared limits | 🔴 Shared limits | 🟡 Depends on setup |
| **Customization** | 🟢 Unlimited | 🔴 Limited | 🔴 None | 🟢 Full control |
| **Support** | 🟢 Community + Pro | 🟡 Email only | 🟡 Basic | 🔴 None |

---

## 💰 **Pricing & Value**

### 💎 **Lifetime License - €79**
*One-time payment, own it forever*

**What You Get:**
- ✅ Complete bot source code
- ✅ Full documentation & setup guide
- ✅ Lifetime updates & bug fixes
- ✅ Community support access
- ✅ Commercial usage rights
- ✅ Multi-language support
- ✅ Priority feature requests

### 🪙 **TON Payment Discount**
**Pay with TON and save 15%!**
- 💰 **TON Price**: €67 (instead of €79)
- 📞 **How to pay**: Contact [@doublegram_official](https://t.me/doublegram_official)
- ⚡ **Fast processing**: License delivered within 24h

### 🎯 **Perfect For:**
- 🎪 **Affiliate Marketers**: Scale your Amazon promotions
- 🏢 **Digital Agencies**: Offer services to clients
- 👨‍💻 **Developers**: Customize and extend functionality
- 🚀 **Entrepreneurs**: Build automated income streams

---

## 🛠️ **Installation**

### Prerequisites
- **License**: Purchase from [doublegram.com/marketplace/affiliate](https://doublegram.com/marketplace/affiliate)
- **Telegram Bot Token**: Create bot via [@BotFather](https://t.me/botfather)
- **OpenAI API Key**: Optional, for AI features
- **Python 3.11+** (for direct installation) or **Docker** (recommended)

### 🐳 **Method 1: Docker Setup (Recommended)**
```bash
# 1. Clone the repository
git clone https://github.com/yourusername/telegram-affiliate-bot.git
cd telegram-affiliate-bot

# 2. Create environment file
cat > .env << EOF
# License Configuration (Required)
LICENSE_CODE=your_license_code_here
DOUBLEGRAM_EMAIL=your_email@domain.com

# Telegram Bot Configuration (Required)
BOT_TOKEN=your_telegram_bot_token_here

# OpenAI Configuration (Optional - for AI features)
OPENAI_API_KEY=your_openai_api_key_here

# God Admin (Required)
GOD_ADMIN_ID=your_telegram_user_id_here
EOF

# 3. Start the bot with Docker
docker-compose up -d

# 4. Check logs
docker-compose logs -f amazonbot
```

### 🐍 **Method 2: Direct Python Installation**
```bash
# 1. Clone the repository
git clone https://github.com/yourusername/telegram-affiliate-bot.git
cd telegram-affiliate-bot

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create environment file
cat > .env << EOF
# License Configuration (Required)
LICENSE_CODE=your_license_code_here
DOUBLEGRAM_EMAIL=your_email@domain.com

# Telegram Bot Configuration (Required)
BOT_TOKEN=your_telegram_bot_token_here

# OpenAI Configuration (Optional - for AI features)
OPENAI_API_KEY=your_openai_api_key_here

# God Admin (Required)
GOD_ADMIN_ID=your_telegram_user_id_here
EOF

# 4. Run the bot
python bot.py
```

### 🔧 **Configuration Details**

#### Required Environment Variables:
- `LICENSE_CODE`: Your license key from Doublegram
- `DOUBLEGRAM_EMAIL`: Email used for license purchase
- `BOT_TOKEN`: Telegram bot token from @BotFather
- `GOD_ADMIN_ID`: Your Telegram user ID (main admin)

#### Optional Environment Variables:
- `OPENAI_API_KEY`: For AI-powered content generation

#### How to Get Your Telegram User ID:
1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. Copy the ID number it sends you
3. Use this as your `GOD_ADMIN_ID`

---

## 📚 **Documentation**

📖 **Coming soon on [doublegram.com/docs](https://doublegram.com/docs)**

---


## 🤝 **Support**

### 📞 **Official Channels**
- 💬 **Telegram Support**: [@doublegram_official](https://t.me/doublegram_official)
- 📢 **News & Updates**: [@doublegram_news](https://t.me/doublegram_news)
- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/yourusername/telegram-affiliate-bot/issues)

---

## 🚀 **Get Started Today**

### 🎯 **Ready to Transform Your Affiliate Marketing?**

1. **[Purchase Your Lifetime License](https://doublegram.com/marketplace/affiliate)** - €79
2. **Clone This Repository** - `git clone ...`
3. **Follow Setup Guide** - 5 minutes to running bot
4. **Start Earning** - Automated affiliate income

### 🎪 **Special Launch Offer**
- ✅ Lifetime license for €79 (normally €149)
- 🪙 **TON Payment**: Only €67 (15% discount!)

[🔗 **GET YOUR LICENSE NOW**](https://doublegram.com/marketplace/affiliate)

---

<div align="center">

**Made with ❤️ by the Doublegram Team**

[Website](https://doublegram.com) • [Marketplace](https://doublegram.com/marketplace) • [News](https://t.me/doublegram_news) • [Support](https://t.me/doublegram_official)

⭐ **Star this repo if you find it useful!** ⭐

</div>
