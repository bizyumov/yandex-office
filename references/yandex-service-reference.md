# Yandex Service Reference

This document is the human-readable and machine-readable reference for Yandex service families and OAuth scopes used by this skill.

Machine-readable conventions:
- `section_key` is the stable group identifier.
- `service_key` is the OAuth scope family key exposed by Yandex OAuth.
- Permissions are listed as raw OAuth suffixes derived from `references/yandex-oauth-scopes.json`.

# Currently Implemented In Skills

- `section_key`: `currently_implemented`

## Yandex Mail / Яндекс Почта

- `service_key`: `mail`
- Description: Email service for sending, receiving, and organizing messages in Yandex 360.
- URL: https://mail.yandex.ru/

### Permissions
- `:imap_full` - Read and delete mailbox messages (IMAP full access) / Чтение и удаление писем в почтовом ящике
- `:imap_ro` - Read mailbox messages (IMAP read-only) / Доступ на чтение писем в почтовом ящике
- `:smtp` - Send emails via Yandex Mail (SMTP) / Отправка писем через Яндекс.Почту по протоколу SMTP

## Yandex Calendar / Яндекс Календарь

- `service_key`: `calendar`
- Description: Online calendar for planning meetings, events, reminders, and shared schedules.
- URL: https://calendar.yandex.ru/

### Permissions
- `:all` - Read and modify calendars and to-do lists / Чтение и изменение содержимого календарей и списков дел

## Yandex Contacts / Яндекс Контакты

- `service_key`: `addressbook`
- Description: Address book service for storing and managing contact data connected to Yandex communication tools.
- URL: https://mail.yandex.ru/#/contacts

### Permissions
- `:all` - Read and modify address book contents / Чтение и изменение содержимого адресной книги

## Yandex Directory / Яндекс Directory

- `service_key`: `directory`
- Description: Organization directory and admin data surface for employees, groups, domains, and org structure in Yandex 360.
- URL: https://yandex.ru/support/yandex-360/business/admin/

### Permissions
- `:manage_dns` - Manage DNS records / Управление DNS-записями
- `:read_departments` - Read department data / Чтение данных о подразделениях
- `:read_domains` - Read organization domain data / Чтение данных о доменах организации
- `:read_external_contacts` - Read external contacts / Чтение внешних контактов
- `:read_groups` - Read group data / Чтение данных о группах
- `:read_organization` - Read user's organization data / Чтение данных об организациях пользователя
- `:read_users` - Read employee data / Чтение данных о сотрудниках
- `:write_departments` - Manage departments / Управление подразделениями
- `:write_domains` - Manage organization domains / Управление доменами организации
- `:write_external_contacts` - Manage external contacts / Управление внешними контактами
- `:write_groups` - Manage groups / Управление группами
- `:write_organization` - Edit organization / Редактирование организации
- `:write_users` - Manage employees / Управление сотрудниками

## Yandex Disk / Яндекс Диск

- `service_key`: `cloud_api`, `yadisk`
- Description: Cloud storage service for storing, syncing, and sharing files through Yandex Disk.
- URL: https://disk.yandex.ru/

### Permissions (`cloud_api`)
- `:disk.app_folder` - Access app folder on Yandex Disk / Доступ к папке приложения на Диске
- `:disk.info` - Access Yandex Disk info / Доступ к информации о Диске
- `:disk.read` - Read entire Yandex Disk / Чтение всего Диска
- `:disk.write` - Write anywhere on Yandex Disk / Запись в любом месте на Диске

### Permissions (`yadisk`)
- `:disk` - Access Yandex Disk for apps / Доступ к Яндекс.Диску для приложений

## Yandex Forms / Яндекс Формы

- `service_key`: `forms`
- Description: Form builder for surveys, applications, quizzes, and data collection workflows.
- URL: https://forms.yandex.ru/admin/

### Permissions
- `:read` - View form settings / Просмотр настроек форм
- `:write` - Modify form settings / Изменение настроек форм

## Yandex Telemost / Яндекс Телемост

- `service_key`: `telemost-api`
- Description: Video meetings and calls service for online conferences and broadcasts.
- URL: https://telemost.yandex.ru/

### Permissions
- `:conferences.create` - Create Telemost meetings and broadcasts / Создание встреч и трансляций в Телемосте
- `:conferences.delete` - Delete Telemost meetings and broadcasts / Удаление встреч и трансляций в Телемосте
- `:conferences.read` - Read Telemost meeting and broadcast data / Чтение данных о встречах и трансляциях в Телемосте
- `:conferences.update` - Edit Telemost meeting and broadcast data / Редактирование данных о встречах и трансляциях в Телемосте

## Yandex Tracker / Яндекс Трекер

- `service_key`: `tracker`
- Description: Work management service for tracking tasks, projects, queues, workflows, and team processes.
- URL: https://tracker.yandex.ru/

### Permissions
- `:read` - Read from Yandex Tracker / Чтение из трекера
- `:write` - Write to Yandex Tracker / Запись в трекер

## Yandex Cloud / Яндекс Облако

- `service_key`: `cloud`
- Description: Cloud platform for infrastructure, managed services, storage, and application deployment.
- URL: https://cloud.yandex.com/

### Permissions
- `:auth` - Authenticate in Yandex Cloud / Аутентификация в Облаке

# Immediate Implementation Scope

- `section_key`: `immediate_scope`

## Yandex Wordstat / Яндекс Вордстат

- `service_key`: `wordstat`
- Description: Keyword statistics service for analyzing search demand and related queries in Yandex.
- URL: https://wordstat.yandex.ru/

### Permissions
- `:api` - Use Yandex Wordstat API / Использование API Вордстата

## Yandex Metrica / Яндекс Метрика

- `service_key`: `metrika`
- Description: Analytics platform for website and app traffic, reports, goals, imports, and raw usage data.
- URL: https://metrika.yandex.ru/

### Permissions
- `:expenses` - Upload expense data / Загрузка расходов
- `:offline_data` - Upload offline data / Загрузка офлайн данных
- `:read` - Read statistics and own/delegated counter settings / Получение статистики, чтение параметров своих и доверенных счётчиков
- `:segments` - Manage user segments / Управление сегментами пользователей
- `:user_params` - Upload user parameters / Загрузка параметров пользователей
- `:write` - Create counters, modify own/delegated counter settings / Создание счётчиков, изменение параметров своих и доверенных счётчиков

## Yandex Webmaster / Яндекс Вебмастер

- `service_key`: `webmaster`
- Description: SEO and site-management service for verification, indexing status, diagnostics, and search visibility.
- URL: https://webmaster.yandex.ru/

### Permissions
- `:hostinfo` - Get external link info for a site / Получение информации о внешних ссылках на сайт
- `:turbopages` - Add Turbo pages for a site / Добавление Турбо-страниц для сайта
- `:verify` - Add sites to Yandex Webmaster, get indexing status / Добавление сайтов в Яндекс.Вебмастер, получение информации о статусе индексирования

# Out Of Scope

- `section_key`: `out_of_scope`

## Addappter / Addappter

- `service_key`: `addappter`
- Description: Existing OAuth scope family for the Addappter partner service. This permission grants access to the Addappter service/API surface; it does not allow creating or defining new OAuth scopes.
- URL: https://yandex.ru/support/addappter-partner/ru/

### Permissions
- `:use` - Use Addappter service / Использование сервиса Addappter

## Adfox / Adfox

- `service_key`: `adfox`
- Description: Advertising management platform for ad serving, monetization, and campaign operations.
- URL: https://yandex.ru/support/adfox/

### Permissions
- `:api` - Use Adfox API / Использование API Adfox

## AppMetrica / AppMetrica

- `service_key`: `appmetrica`
- Description: Mobile analytics and attribution platform covering traffic, product metrics, crashes, and push campaigns.
- URL: https://yandex.ru/dev/appmetrica/

### Permissions
- `:read` - Access AppMetrica app statistics and read app configuration parameters / Доступ к статистике приложений в AppMetrica, получение параметров настройки приложений
- `:write` - Create AppMetrica apps and modify their configuration / Создание приложений в AppMetrica и изменение параметров их настройки

## Yandex Audience / Яндекс Аудитории

- `service_key`: `audience`
- Description: Audience segmentation service that combines first-party and Yandex data for ad targeting and look-alike scenarios.
- URL: https://yandex.ru/support2/audience/ru/

### Permissions
- `:read` - Read own and delegated segment configuration / Чтение параметров настройки своих и доверенных сегментов
- `:write` - Create segments, modify own and delegated segment configuration / Создание сегментов, изменение параметров настройки своих и доверенных сегментов

## Yandex Bot Platform / Платформа ботов Яндекса

- `service_key`: `botplatform`
- Description: Existing OAuth scope family for Yandex 360 Messenger bot operations. These permissions let a bot read chat-related data and send messages/media; they do not allow creating or defining new OAuth scopes.
- URL: https://yandex.ru/support/yandex-360/business/admin/ru/messenger/bot-platform

### Permissions
- `:read` - Bot reads chat messages, chat data, users, groups and departments / Чтение ботом сообщений чата, данных по чатам, пользователям, группам и департаментам
- `:write` - Bot sends messages and media to chat / Отправка ботом сообщений и медиа данных в чат

## Banner Storage / Хранилище баннеров

- `service_key`: `bsapi`
- Description: Adfox banner inventory area for storing, listing, and configuring banner creatives and banner types.
- URL: https://yandex.ru/support/adfox/ru/banners/banner-list

### Permissions
- `:access` - Access Banner Storage / Доступ к Хранилищу Баннеров

## Yandex Charging Stations / Зарядки Яндекса

- `service_key`: `chargers`
- Description: Electric vehicle charging feature in Yandex Refuel for finding stations, starting sessions, and paying for charging.
- URL: https://yandex.ru/support/zapravki/ru/how-to-charge

### Permissions
- `:write` - Use charging stations / Использование зарядок

## Yandex Caller ID / Яндекс АОН

- `service_key`: `cid`
- Description: Caller identification service that helps recognize incoming calls and numbers.
- URL: https://yandex.ru/support/caller-id/ru/

### Permissions
- `:use` - Use Yandex Caller ID / Использование Яндекс.АОН

## Priority Business Listing API / API приоритетного размещения организаций

- `service_key`: `clients`
- Description: Yandex Business promotion format that increases a company profile's visibility in Maps, Navigator, and search results.
- URL: https://yandex.ru/support/business-priority/ru/benefits

### Permissions
- `:priority.api` - Use Priority Business Listing API / Использование API Приоритетного размещения организаций

## Yandex Contests / Соревнования Яндекса

- `service_key`: `contest`
- Description: Competitive programming platform for running contests, checking submissions, and managing participants.
- URL: https://contest.yandex.ru/

### Permissions
- `:manage` - Manage contests and participants / Управление соревнованиями и участниками
- `:submit` - Submit and test solutions in contests / Отправка и тестирование решений на соревнованиях

## Courier Logistics / Логистика курьеров

- `service_key`: `courier`
- Description: RouteQ courier and Track & Trace toolkit for courier operations, routes, and delivery monitoring.
- URL: https://yandex.ru/routing/doc/en/courier-app/

### Permissions
- `:logistician` - Download courier and order data, upload results / Загрузка данных о курьерах и заказах, выгрузка результатов

## Yandex Delivery Partner API / API Яндекс Доставки для партнёров

- `service_key`: `delivery`
- Description: Partner API for integrating deliveries, order flow, and logistics with Yandex Delivery.
- URL: https://yandex.ru/dev/delivery/

### Permissions
- `:partner-api` - Use Yandex Delivery Partner API / Использование API Яндекс.Доставки для партнеров

## Yandex Direct / Яндекс Директ

- `service_key`: `direct`
- Description: Advertising platform for promoting products and services across Yandex search and ad network inventory.
- URL: https://direct.yandex.ru/

### Permissions
- `:api` - Use Yandex Direct API / Использование API Яндекс.Директа

## Yandex Distribution API / API дистрибуции Яндекса

- `service_key`: `distribution`
- Description: Partner API for distribution statistics and reporting used by Yandex commercial and software-distribution partners.
- URL: https://yandex.ru/dev/distribution/

### Permissions
- `:all` - Use Yandex Distribution API / Использование API дистрибуции Яндекса

## Doctors and Clinics Reports / Отчёты врачей и клиник

- `service_key`: `doctors-clinics`
- Description: Healthcare discovery service for finding doctors and clinics, with partner-side data exchange around clinic information and reporting.
- URL: https://yandex.ru/medicine/

### Permissions
- `:write_reports` - Submit reports / Передача отчётов

## Yandex Smart Home / Умный дом Яндекса

- `service_key`: `iot`
- Description: Smart home platform for connected devices, control actions, and device-state integrations.
- URL: https://yandex.ru/dev/dialogs/smart-home/

### Permissions
- `:control` - Control smart home devices / Управление устройствами умного дома
- `:view` - View smart home device list / Просмотр списка устройств умного дома

## Yandex ID / Яндекс ID

- `service_key`: `login`
- Description: Identity and profile API for user authorization and access to profile fields such as email, avatar, and phone.
- URL: https://yandex.ru/dev/id/doc/ru/

### Permissions
- `:address.all.read` - Access all addresses (for quick delivery orders) / Доступ к адресам – для быстрого заказа доставки
- `:address.home_work.read` - Access home and work addresses / Доступ к домашнему и рабочему адресам
- `:avatar` - Access user avatar / Доступ к портрету пользователя
- `:birthday` - Access date of birth / Доступ к дате рождения
- `:default_phone` - Access phone number / Доступ к номеру телефона
- `:email` - Access email address / Доступ к адресу электронной почты
- `:info` - Access login, first/last name, gender / Доступ к логину, имени и фамилии, полу
- `:promo_subscription` - Consent to receive promotional messages from this app / Даю согласие на получение рекламных сообщений от данного

## Yandex Market / Яндекс Маркет

- `service_key`: `market`
- Description: Marketplace and product platform for merchants, catalogs, and partner integrations.
- URL: https://yandex.ru/dev/market/partner-api/

### Permissions
- `:partner-api` - Yandex Market / Product Search Partner API / API Яндекс.Маркета / Поиска по товарам для партнеров

## Shedevrum API / API Шедеврума

- `service_key`: `masterpiecer`
- Description: Generative AI service for creating and publishing images and videos from text prompts in Shedevrum.
- URL: https://yandex.ru/support/shedevrum/ru/faq

### Permissions
- `:all` - Access Shedevrus API / Доступ к API Шедеврус

## MediaMetrica / МедиаМетрика

- `service_key`: `mediametrika`
- Description: Advertising analytics API for campaign statistics, advertiser settings, and media-campaign management.
- URL: https://yandex.ru/dev/admetrica/doc/ru/

### Permissions
- `:read` - Read statistics and own/delegated advertiser & campaign settings / Получение статистики, чтение параметров своих и доверенных рекламодателей и рекламных кампаний
- `:write` - Create campaigns, modify own/delegated advertiser & campaign settings / Создание рекламных кампаний, изменение параметров своих и доверенных рекламодателей и рекламных кампаний

## Yandex Messenger / Яндекс Мессенджер

- `service_key`: `messenger`
- Description: Corporate and personal messaging service inside Yandex 360.
- URL: https://360.yandex.ru/business/messenger/

### Permissions
- `:vconf` - Use Messenger chat / Использование чата Мессенджера

## Neuro Expert / Нейроэксперт

- `service_key`: `neuro-expert`
- Description: AI knowledge-base assistant referenced by Yandex as a tool for working with uploaded materials and finding facts in them.
- URL: https://yandex.ru/company/news/11-08-2025-02

### Permissions
- `:all` - Access Neuro Expert / Доступ к Нейроэксперту

## Partner Office API / API партнёрского кабинета

- `service_key`: `partner_office`
- Description: Partner-office and advertising-markup surface used by Yandex partner cabinets and ad-labeling workflows.
- URL: https://yandex.ru/support2/ord/ru/api/connect

### Permissions
- `:advmarkup` - Use Ad Markup API / Использование API маркировки рекламы
- `:api` - Use Agency Partner Office API / Использование API партнёрского кабинета для агентств

## Yandex ID Organizations / Организации Yandex ID

- `service_key`: `passport`
- Description: Organization and federation management layer tied to Yandex ID identity administration.
- URL: https://yandex.ru/dev/id/doc/ru/

### Permissions
- `:business` - Manage Yandex ID organizations / Работа с организациями Яндекс ID
- `:scim-api.all` - Manage federations / Управление федерациями

## Yandex Partner Interface / Партнёрский интерфейс Яндекса

- `service_key`: `pi`
- Description: Partner API surface for Yandex advertising and publisher inventory operations.
- URL: https://yandex.ru/dev/partner/

### Permissions
- `:access-ad-inventory-api` - Access Ad Inventory Management API / Доступ к API управления рекламным инвентарём
- `:all` - Use Yandex Partner Interface API / Использование API партнёрского интерфейса Яндекса

## Yandex Plus / Яндекс Плюс

- `service_key`: `plus`
- Description: Subscription service that bundles paid benefits, perks, and partner options across Yandex products.
- URL: https://plus.yandex.ru/

### Permissions
- `:use-benefits-and-options` - Interact with Yandex Plus benefits and options / Взаимодействие с функциональностью бенефитов и опций Плюса
- `:use-opk-subscriptions` - Interact with Yandex Plus OPK subscriptions / Взаимодействие с ОПК-подписками Плюса

## Product Search Partner API / API поиска по товарам для партнёров

- `service_key`: `products`
- Description: Partner API for managing shop offers and data used in Yandex product search.
- URL: https://yandex.ru/dev/products/doc/ru/

### Permissions
- `:partner-api` - Product Search Partner API / API Поиска по товарам для партнеров

## Yandex Promopages / Яндекс ПромоСтраницы

- `service_key`: `promopages`
- Description: Content promotion platform for branded editorial landing pages and sponsored distribution.
- URL: https://yandex.ru/promo-pages/

### Permissions
- `:api` - Use Yandex Promopages API / Использование API Яндекс.ПромоСтраниц

## Smart Device Infrastructure / Инфраструктура умных устройств

- `service_key`: `smartdevicesinfrastructur`
- Description: Device platform and support surface for Alice smart devices and connected Yandex hardware.
- URL: https://alice.yandex.ru/support/ru/feedback

### Permissions
- `:read` - Access device information / Доступ к информации об устройстве
- `:write_service_info` - Write device repair information / Запись информации о ремонтах девайсов

## Yandex Split / Яндекс Сплит

- `service_key`: `split`
- Description: Split-payment product for installment-like payments and checkout financing.
- URL: https://split.yandex.ru/

### Permissions
- `:api` - Create split-payment requests / Создание заявок на оплату частями

## Yandex Business Directory / Яндекс Справочник

- `service_key`: `sprav`
- Description: Business listing and organization directory service for company profiles and location data.
- URL: https://yandex.ru/support/business-priority/ru/sprav/

### Permissions
- `:all` - Use Yandex Business Directory / Использование Справочника

## Yandex Search Suggestions / Подсказки Яндекса

- `service_key`: `suggest`
- Description: Search-suggestion feature that shows predicted queries and quick answers while users type in Yandex search.
- URL: https://yandex.ru/support/search/ru/troubleshooting/searchsettings/suggest

### Permissions
- `:read_web_history` - Read search query history / Чтение истории запросов

## Yandex TV Program / Телепрограмма Яндекса

- `service_key`: `tv`
- Description: Electronic program guide for TV channels, schedules, and broadcast discovery.
- URL: https://tv.yandex.ru/

### Permissions
- `:use` - Use TV program / Использование телепрограммы

## Vendor Model APIs / API моделей вендоров

- `service_key`: `vendors`
- Description: Merchant and catalog tooling around vendor, model, and product-card data in Yandex product search.
- URL: https://yandex.ru/support/merchants/ru/elements/vendor-name-model

### Permissions
- `:model-bid.read` - View vendor model bids / Просмотр ставок на модели вендоров
- `:model-bid.write` - Set vendor model bids / Выставление ставок на модели вендоров
- `:model-edit.params` - View category and model parameters / Просмотр параметров категорий и моделей
- `:model-edit.requests` - Manage model edit requests / Работа с заявками на редактирование моделей

## Yandex Wiki / Яндекс Вики

- `service_key`: `wiki`
- Description: Collaborative knowledge base and documentation workspace inside Yandex 360.
- URL: https://yandex.ru/support/wiki/ru/

### Permissions
- `:read` - Read from Yandex Wiki / Чтение из Вики
- `:write` - Write to Yandex Wiki / Запись в Вики

## Notification Transport API / API транспорта нотификаций

- `service_key`: `xiva`
- Description: Internal Yandex notifications platform responsible for delivering service notifications to users.
- URL: https://infra.yandex.ru/notifications

### Permissions
- `:use_api` - Use Notification Transport API / Использование API транспорта нотификаций

## Yandex 360 Admin / Яндекс 360 Админ

- `service_key`: `ya360_admin`
- Description: Administrative surface for organization-wide mail, routing, mailbox, and product settings in Yandex 360.
- URL: https://yandex.ru/support/yandex-360/business/admin/

### Permissions
- `:mail_read_antispam_settings` - Read organization antispam settings / Чтение настроек Антиспама для организации
- `:mail_read_domain_routes` - Read organization mail routing rules / Чтение правил маршрутизации организации
- `:mail_read_mail_list_permissions` - View mailing list permissions / Просмотр разрешений на рассылку
- `:mail_read_organization_settings` - Read organization mail settings / Чтение настроек почты организации
- `:mail_read_routing_rules` - Read domain mail processing rules / Чтение правил обработки почты для домена
- `:mail_read_shared_mailbox_inventory` - Read Shared Mailbox Registry / Чтение Реестра Общих Ящиков
- `:mail_read_user_settings` - Read user mail settings / Чтение настроек почты пользователя
- `:mail_write_antispam_settings` - Manage organization antispam settings / Управление настройками Антиспама для организации
- `:mail_write_domain_routes` - Manage organization mail routing rules / Управление правилами маршрутизации организации
- `:mail_write_mail_list_permissions` - Modify mailing list permissions / Изменение разрешений на рассылку
- `:mail_write_organization_settings` - Manage organization mail settings / Управление настройками почты организации
- `:mail_write_routing_rules` - Manage domain mail processing rules / Управление правилами обработки почты для домена
- `:mail_write_shared_mailbox_inventory` - Edit Shared Mailbox Registry / Редактирование Реестра Общих Ящиков
- `:mail_write_user_settings` - Manage user mail settings / Управление настройками почты пользователя

## Yandex 360 Data / Яндекс 360 Данные

- `service_key`: `ya360_data`
- Description: Yandex 360 product usage and reporting data surface for organizations.
- URL: https://yandex.ru/support/yandex-360/business/admin/

### Permissions
- `:read_reports` - Read Yandex 360 product usage statistics / Получения статистики использования продуктов Яндекс 360

## Yandex 360 Security / Яндекс 360 Безопасность

- `service_key`: `ya360_security`
- Description: Security administration surface for audit logs, sessions, passwords, and service applications in Yandex 360.
- URL: https://yandex.ru/support/yandex-360/business/admin/

### Permissions
- `:audit_log_disk` - Read Disk audit log events / Чтение событий аудит лога Диска
- `:audit_log_mail` - Read Mail audit log events / Чтение событий аудит лога Почты
- `:domain_2fa_write` - Manage mandatory 2FA for users / Управление обязательной 2FA для пользователей
- `:domain_passwords_read` - Read user password settings / Чтение информации о настройках паролей пользователей
- `:domain_passwords_write` - Manage user password settings / Управление настройками паролей пользователей
- `:domain_sessions_read` - Read user session settings / Чтение информации о настройках сессий пользователей
- `:domain_sessions_write` - Manage user session and auth session settings / Управление настройками и авторизационными сессиями пользователей
- `:domain_settings_read` - Read organization security settings / Чтение информации о настройках безопасности организации
- `:domain_settings_write` - Manage organization security settings / Управление настройками безопасности организации
- `:read_auditlog` - Read audit log events / Чтение событий аудитлога
- `:service_applications_read` - Read service applications list / Чтение списка сервисных приложений
- `:service_applications_write` - Manage service applications list / Управление списком сервисных приложений

## Yandex Chats / Чаты Яндекса

- `service_key`: `yamb`
- Description: Chat functionality in Yandex Messenger for direct and group communication, files, and public chat links.
- URL: https://yandex.ru/support/yandex-360/customers/messenger/ru/chat-for-users

### Permissions
- `:all` - Read and send chat messages / Чтение и отправка сообщений в чатах

## Yandex Pay / Яндекс Pay

- `service_key`: `yandexpay`
- Description: Payment service for checkout, saved payment methods, and merchant integrations.
- URL: https://pay.yandex.ru/

### Permissions
- `:all` - Pay via Yandex Pay / Оплата через Yandex Pay
- `:external` - Pay with cards and accounts linked to Yandex ID / Оплата картами и счетами, привязанными в Яндекс ID
- `:merchant-api` - Manage Yandex Pay Checkout orders / Управление заказами Yandex Pay Checkout

## Yandex Store / Яндекс Store

- `service_key`: `yastore`
- Description: Historical Yandex Android app-store product referenced in Yandex corporate materials; current public developer documentation is not readily available.
- URL: https://yandex.ru/company/history

### Permissions
- `:publisher` - Access Yandex Store API for Android developers / Доступ к API Яндекс.Store для Android-разработчиков

## Yandex Tag Manager / Яндекс Tag Manager

- `service_key`: `ytm`
- Description: Tag management system with template APIs, data-layer access, and event-handling interfaces.
- URL: https://yandex.ru/support/ytm/ru/templates/guide/api

### Permissions
- `:read` - Read tags, triggers, variables, and templates / Получение информации о тегах, триггерах, переменных, шаблонах

## Zen Promo / Дзен Промо

- `service_key`: `zen`
- Description: Legacy Dzen promotional analytics scope; current public Yandex materials now center the adjacent Promopages product rather than a standalone Zen Promo API.
- URL: https://yandex.ru/promo-pages/

### Permissions
- `:promo.read` - Read Zen Promo statistics / Получение статистики по Дзен Промо

# Scope Extraction Appendix

The section below preserves the extraction workflow used to build `references/yandex-oauth-scopes.json`.

# How to Extract Yandex OAuth Scopes

## Source

The full list of OAuth scopes (permissions) is embedded in the **Apollo Client cache** on the Yandex OAuth app registration page. It is NOT available via a public API endpoint — the data comes as a GraphQL response during server-side rendering.

## Steps

1. **Open the OAuth app creation page** (requires Yandex login):
   ```
   https://oauth.yandex.ru/client/new/api
   ```

2. **Open browser DevTools** → Console (F12)

3. **Extract scopes from Apollo cache**:
   ```js
   copy(JSON.stringify(
     Object.values(window.__APOLLO_CLIENT__.cache.extract())
       .filter(v => v.__typename === 'OAuthScope')
       .map(v => ({id: v.id, title: v.title, tags: v.tags, requiresApproval: v.requiresApproval}))
       .sort((a, b) => a.id.localeCompare(b.id)),
     null, 2
   ))
   ```
   This copies the full JSON to clipboard.

4. **Paste** into a `.json` file.

## Output Format

Each entry:
```json
{
  "id": "cloud_api:disk.read",
  "title": "Чтение всего Диска",
  "tags": [],
  "requiresApproval": false
}
```

## Notes

- The page uses **React + Apollo GraphQL**. The `__APOLLO_CLIENT__` global holds the cache.
- No network requests are made when typing in the "Доступ к данным" field — filtering is client-side.
- Scope list may change over time. Re-run to get the latest version.
- As of 2026-04-02 there are **134 scopes**.
- The GraphQL query is fired on page load (SSR hydration); the full list lands in Apollo cache before any user interaction.

## Automation (curl-based)

Not directly reproducible via curl because the page requires authentication and the scope data is injected during SSR. However, you can use a headless browser with cookies:

```bash
# With a logged-in session cookie, fetch the page and extract via JS:
node -e "
const puppeteer = require('puppeteer');
(async () => {
  const browser = await puppeteer.launch({headless: true});
  const page = await browser.newPage();
  // Load cookies from file or set them manually
  await page.goto('https://oauth.yandex.ru/client/new/api', {waitUntil: 'networkidle0'});
  const scopes = await page.evaluate(() => {
    return Object.values(window.__APOLLO_CLIENT__.cache.extract())
      .filter(v => v.__typename === 'OAuthScope')
      .map(v => ({id: v.id, title: v.title, tags: v.tags, requiresApproval: v.requiresApproval}))
      .sort((a, b) => a.id.localeCompare(b.id));
  });
  console.log(JSON.stringify(scopes, null, 2));
  await browser.close();
})();
"
```
