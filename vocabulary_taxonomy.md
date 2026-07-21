# Vocabulary Topic Taxonomy

This taxonomy provides a shared set of semantic topics for vocabulary notes across
languages. It is intended for Anki tags, filtered decks, AI-assisted vocabulary
generation, and bulk classification.

## Assignment Rules

- Assign exactly one primary topic to each vocabulary item.
- Classify the selected meaning of the word or expression, not every possible sense.
- Use a prompt hint or existing definition to disambiguate homonyms and polysemous words.
- Prefer the topic in which a learner is most likely to encounter or use the selected sense.
- Use `topic::core_general` when a word has no strong subject area. Do not force general
  verbs, adjectives, adverbs, connectors, or grammatical expressions into an arbitrary topic.
- Keep topic independent of part of speech, difficulty, source, and language.
- Use the canonical tag names below so filtered decks remain consistent across languages.

## Canonical Topics

| Tag | Display name | Scope |
|---|---|---|
| `topic::core_general` | Core & General | General-purpose verbs, adjectives, adverbs, connectors, quantities, and other vocabulary without a strong subject area. |
| `topic::people_relationships` | People & Relationships | Family, friends, social roles, relationships, and interactions between people. |
| `topic::home_daily_life` | Home & Daily Life | Rooms, household objects, chores, domestic activities, and everyday routines. |
| `topic::food_drink` | Food & Drink | Ingredients, meals, beverages, cooking, dining, and restaurants. |
| `topic::health_body` | Health & Body | Anatomy, physical conditions, symptoms, healthcare, medicine, and wellbeing. |
| `topic::school_learning` | School & Learning | Education, studying, academic subjects, classrooms, teaching, and learning activities. |
| `topic::work_business` | Work & Business | Jobs, workplaces, professions, organizations, commerce, and professional activities. |
| `topic::shopping_money` | Shopping & Money | Products, stores, prices, purchases, payments, banking, and personal finance. |
| `topic::travel_transport` | Travel & Transport | Vehicles, transit, journeys, tourism, tickets, luggage, and accommodation. |
| `topic::places_directions` | Places & Directions | Buildings, public places, geographic position, spatial relationships, routes, and navigation. |
| `topic::nature_environment` | Nature & Environment | Animals, plants, landscapes, natural materials, ecology, and environmental issues. |
| `topic::time` | Time | Dates, periods, duration, frequency, sequence, schedules, and temporal relationships. |
| `topic::weather_climate` | Weather & Climate | Weather conditions, temperature, precipitation, seasons, forecasts, and climate. |
| `topic::communication_language` | Communication & Language | Speaking, listening, writing, reading, messages, language, and communication media. |
| `topic::feelings_personality` | Feelings & Personality | Emotions, moods, attitudes, character traits, and personal qualities. |
| `topic::clothing_appearance` | Clothing & Appearance | Clothes, accessories, physical appearance, grooming, and personal presentation. |
| `topic::leisure_entertainment` | Leisure & Entertainment | Hobbies, sports, games, arts, music, literature, television, and recreation. |
| `topic::society_public_life` | Society & Public Life | Government, law, public institutions, community, social issues, and civic life. |
| `topic::technology` | Technology | Devices, computing, software, the internet, digital services, and technical actions. |

## Boundary Guidelines

- **Travel & Transport vs. Places & Directions:** use Travel & Transport for the journey
  or means of travel; use Places & Directions for the destination, location, or navigation.
- **Work & Business vs. Shopping & Money:** use Work & Business for professional or
  organizational activity; use Shopping & Money for consumer transactions and personal finance.
- **Communication & Language vs. Technology:** use Communication & Language for the act
  or content of communication; use Technology when the device, platform, or technical process
  is central.
- **People & Relationships vs. Feelings & Personality:** use People & Relationships for a
  social role or interpersonal relationship; use Feelings & Personality for an internal state
  or personal characteristic.
- **Home & Daily Life vs. other concrete topics:** use a more specific topic such as Food &
  Drink or Clothing & Appearance when that subject is central; otherwise use Home & Daily Life.
- **Time vs. Weather & Climate:** seasons belong to Weather & Climate when describing climate
  or seasonal conditions, and to Time when used primarily as calendar periods.
- **Core & General vs. a concrete topic:** choose a concrete topic only when the selected sense
  has a clear, characteristic association with it.

## Suggested AI Output

Return the canonical tag in the optional `Tags` key:

```json
{
  "success": true,
  "Tags": ["topic::health_body"]
}
```

Other tag dimensions, such as language, level, source, or part of speech, should use
separate conventions and are outside this topic taxonomy.
