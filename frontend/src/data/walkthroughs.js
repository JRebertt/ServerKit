// Guided UI outcomes. Recipes automate server work; walkthroughs guide the
// operator through product controls where intent or a human-held secret is
// required. Stable ids are persisted, so never rename one without a migration.
export const WALKTHROUGHS = Object.freeze([
    {
        id: 'create-service',
        icon: 'service',
        tone: 'cyan',
        titleKey: 'app.walkthroughs.createServiceTitle',
        title: 'Create your first service',
        descriptionKey: 'app.walkthroughs.createServiceDescription',
        description: 'Choose a source, review the detected runtime, and launch a service.',
        durationKey: 'app.walkthroughs.fiveMinutes',
        duration: 'About 5 minutes',
        permission: { feature: 'applications', level: 'write' },
        steps: [
            {
                id: 'open-wizard',
                titleKey: 'app.walkthroughs.openServiceWizard',
                title: 'Open the service wizard',
                descriptionKey: 'app.walkthroughs.openServiceWizardDescription',
                description: 'Start from ServerKit’s dedicated three-step service flow.',
                path: '/services/new',
                route: '/services/new',
                target: '[data-walkthrough="new-service"]',
                actionKey: 'app.walkthroughs.openWizard',
                action: 'Open wizard',
            },
            {
                id: 'choose-source',
                titleKey: 'app.walkthroughs.chooseServiceSource',
                title: 'Choose where the code lives',
                descriptionKey: 'app.walkthroughs.chooseServiceSourceDescription',
                description: 'Pick GitHub, another Git remote, a local path, or a ZIP upload.',
                path: '/services/new',
                signal: 'service-source-selected',
                target: '[data-walkthrough="service-sources"]',
                actionKey: 'app.walkthroughs.chooseSource',
                action: 'Choose a source',
            },
            {
                id: 'review-service',
                titleKey: 'app.walkthroughs.reviewService',
                title: 'Review the detected setup',
                descriptionKey: 'app.walkthroughs.reviewServiceDescription',
                description: 'Confirm the name, runtime, build method, project, and environment.',
                path: '/services/new',
                signal: 'service-review-ready',
                target: '[data-walkthrough="service-review"]',
                actionKey: 'app.walkthroughs.continueSetup',
                action: 'Continue setup',
            },
            {
                id: 'create-service',
                titleKey: 'app.walkthroughs.launchService',
                title: 'Create and launch the service',
                descriptionKey: 'app.walkthroughs.launchServiceDescription',
                description: 'Submit the reviewed configuration. The guide completes only after creation succeeds.',
                path: '/services/new',
                signal: 'service-created',
                target: '[data-walkthrough="service-submit"]',
                actionKey: 'app.walkthroughs.finishService',
                action: 'Finish in the wizard',
            },
        ],
    },
    {
        id: 'enable-two-factor',
        icon: 'security',
        tone: 'amber',
        titleKey: 'app.walkthroughs.enableTwoFactorTitle',
        title: 'Enable two-step authentication',
        descriptionKey: 'app.walkthroughs.enableTwoFactorDescription',
        description: 'Pair an authenticator, verify a code, and store your recovery codes.',
        durationKey: 'app.walkthroughs.threeMinutes',
        duration: 'About 3 minutes',
        steps: [
            {
                id: 'open-security',
                titleKey: 'app.walkthroughs.openSecuritySettings',
                title: 'Open account security',
                descriptionKey: 'app.walkthroughs.openSecuritySettingsDescription',
                description: 'Go directly to your personal two-factor authentication card.',
                path: '/settings/security?focus=setting:security-2fa',
                route: '/settings/security',
                target: '[data-walkthrough="two-factor-card"]',
                actionKey: 'app.walkthroughs.openSecurity',
                action: 'Open security',
            },
            {
                id: 'pair-authenticator',
                titleKey: 'app.walkthroughs.pairAuthenticator',
                title: 'Pair your authenticator',
                descriptionKey: 'app.walkthroughs.pairAuthenticatorDescription',
                description: 'Scan the QR code, then enter the six-digit code from your app.',
                path: '/settings/security?focus=setting:security-2fa',
                signal: 'two-factor-setup-started',
                target: '[data-walkthrough="two-factor-card"]',
                actionKey: 'app.walkthroughs.startEnrollment',
                action: 'Start enrollment',
            },
            {
                id: 'verify-two-factor',
                titleKey: 'app.walkthroughs.verifyAndSaveCodes',
                title: 'Verify and save recovery codes',
                descriptionKey: 'app.walkthroughs.verifyAndSaveCodesDescription',
                description: 'The guide verifies the live account status—it never stores your code or secret.',
                path: '/settings/security?focus=setting:security-2fa',
                signal: 'two-factor-enabled',
                check: 'two-factor-enabled',
                target: '[data-walkthrough="two-factor-verify"]',
                actionKey: 'app.walkthroughs.checkStatus',
                action: 'Check status',
            },
        ],
    },
]);

export const WALKTHROUGH_BY_ID = Object.freeze(Object.fromEntries(
    WALKTHROUGHS.map((walkthrough) => [walkthrough.id, walkthrough]),
));

// Keep every translation key literal for the i18n extraction gate while the
// execution registry above stays stable and locale-neutral.
export function localizeWalkthroughs(t) {
    const copy = {
        'create-service': {
            title: t('app.walkthroughs.createServiceTitle', 'Create your first service'),
            description: t('app.walkthroughs.createServiceDescription', 'Choose a source, review the detected runtime, and launch a service.'),
            duration: t('app.walkthroughs.fiveMinutes', 'About 5 minutes'),
            steps: [
                {
                    title: t('app.walkthroughs.openServiceWizard', 'Open the service wizard'),
                    description: t('app.walkthroughs.openServiceWizardDescription', 'Start from ServerKit’s dedicated three-step service flow.'),
                    action: t('app.walkthroughs.openWizard', 'Open wizard'),
                },
                {
                    title: t('app.walkthroughs.chooseServiceSource', 'Choose where the code lives'),
                    description: t('app.walkthroughs.chooseServiceSourceDescription', 'Pick GitHub, another Git remote, a local path, or a ZIP upload.'),
                    action: t('app.walkthroughs.chooseSource', 'Choose a source'),
                },
                {
                    title: t('app.walkthroughs.reviewService', 'Review the detected setup'),
                    description: t('app.walkthroughs.reviewServiceDescription', 'Confirm the name, runtime, build method, project, and environment.'),
                    action: t('app.walkthroughs.continueSetup', 'Continue setup'),
                },
                {
                    title: t('app.walkthroughs.launchService', 'Create and launch the service'),
                    description: t('app.walkthroughs.launchServiceDescription', 'Submit the reviewed configuration. The guide completes only after creation succeeds.'),
                    action: t('app.walkthroughs.finishService', 'Finish in the wizard'),
                },
            ],
        },
        'enable-two-factor': {
            title: t('app.walkthroughs.enableTwoFactorTitle', 'Enable two-step authentication'),
            description: t('app.walkthroughs.enableTwoFactorDescription', 'Pair an authenticator, verify a code, and store your recovery codes.'),
            duration: t('app.walkthroughs.threeMinutes', 'About 3 minutes'),
            steps: [
                {
                    title: t('app.walkthroughs.openSecuritySettings', 'Open account security'),
                    description: t('app.walkthroughs.openSecuritySettingsDescription', 'Go directly to your personal two-factor authentication card.'),
                    action: t('app.walkthroughs.openSecurity', 'Open security'),
                },
                {
                    title: t('app.walkthroughs.pairAuthenticator', 'Pair your authenticator'),
                    description: t('app.walkthroughs.pairAuthenticatorDescription', 'Scan the QR code, then enter the six-digit code from your app.'),
                    action: t('app.walkthroughs.startEnrollment', 'Start enrollment'),
                },
                {
                    title: t('app.walkthroughs.verifyAndSaveCodes', 'Verify and save recovery codes'),
                    description: t('app.walkthroughs.verifyAndSaveCodesDescription', 'The guide verifies the live account status—it never stores your code or secret.'),
                    action: t('app.walkthroughs.checkStatus', 'Check status'),
                },
            ],
        },
    };

    return WALKTHROUGHS.map((walkthrough) => {
        const localized = copy[walkthrough.id];
        return {
            ...walkthrough,
            ...localized,
            steps: walkthrough.steps.map((step, index) => ({
                ...step,
                ...localized.steps[index],
            })),
        };
    });
}
