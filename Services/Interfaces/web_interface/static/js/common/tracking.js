
$(document).ready(function() {

    const getUserEmail = () => {
        return getUserDetails().email
    }

    const getUserDetails = () => {
        return _USER_DETAILS
    }

    const updateUserDetails = () => {
        posthog.capture(
            getUserEmail(),
            event='update_user_details',
            properties={
                '$set': getUserDetails(),
            }
        )
    }

    const shouldUpdateUserDetails = () => {
        const currentProperties = posthog.get_property('$stored_person_properties');
        return (
            getUserEmail() !== ""
            && isDefined(currentProperties)
            && JSON.stringify(currentProperties) !== JSON.stringify(getUserDetails())
        )
    }

    const shouldReset = (newEmail) => {
        const previousId = posthog.get_distinct_id();
        return (
            newEmail !== previousId
            // if @ is the user id, it's an email which is different from the current one: this is a new user
            && previousId.indexOf("@") !== -1
        );
    }

    const identify = (email) => {
        posthog.identify(
            email,
            getUserDetails() // optional: set additional person properties
        );
    }

    const updateUserIfNecessary = () => {
        if (!_IS_ALLOWING_TRACKING){
            // tracking disabled
            return
        }
        const email = getUserEmail();
        if (email !== "" && posthog.get_distinct_id() !== email){
            if (shouldReset(email)){
                // If you also want to reset the device_id so that the device will be considered a new device in
                // future events, you can pass true as an argument
                // => past events will be bound to the current user as soon as he connects but avoid binding later events
                // in case the user changes
                console.log("PH: Resetting user")
                const resetDeviceId = true
                posthog.reset(resetDeviceId);
            }
            // new authenticated email: identify
            console.log("PH: Identifying user")
            identify(email);
        }else{
            if (shouldUpdateUserDetails()){
                console.log("PH: updating user details")
                updateUserDetails();
            }
        }
    }

    updateUserIfNecessary();
});
